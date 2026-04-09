"""Core medication service — prescription + medication lifecycle management."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lib.core.postgres_store import PostgresStore
from lib.models.patient import Patient
from lib.models.patient_medication import PatientMedication
from lib.models.patient_prescription import PatientPrescription
from lib.schemas.medication import (
    ConfirmPrescriptionRequest,
    ConfirmedMedicine,
    MedicationListResponse,
    MedicationResponse,
    PrescriptionResponse,
)
from lib.services.vector.medication.service import MedicationVectorService
from lib.utils.postgres_session_decorator import with_postgres_session

logger = logging.getLogger(__name__)


class MedicationService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        medication_vector_service: MedicationVectorService,
    ):
        self.postgres_store = postgres_store
        self.medication_vector_service = medication_vector_service

    # ── Prescription + Medication creation ────────────────────────────────

    # ── Draft ─────────────────────────────────────────────────────────────

    @with_postgres_session
    async def save_draft_prescription(
        self,
        patient_id: str,
        file_urls: list[str],
        extracted_data: dict,
        uploaded_by_id: str,
        uploaded_by_type: str,
        *,
        postgres_session: AsyncSession,
    ) -> PatientPrescription:
        """Save a draft prescription with LLM-extracted data. No medications created yet."""
        # Check for duplicate draft with same file_urls
        if file_urls:
            result = await postgres_session.execute(
                select(PatientPrescription).where(
                    PatientPrescription.patient_id == patient_id,
                    PatientPrescription.file_urls == file_urls,
                )
            )
            existing = result.scalars().first()
            if existing:
                # Update extraction data on existing draft
                existing.extracted_data = extracted_data
                existing.updated_at = datetime.now().replace(tzinfo=None)
                await postgres_session.commit()
                return existing

        prescription = PatientPrescription(
            patient_id=patient_id,
            file_urls=file_urls,
            status="draft",
            extracted_data=extracted_data,
            uploaded_by_id=uploaded_by_id,
            uploaded_by_type=uploaded_by_type,
        )
        postgres_session.add(prescription)
        await postgres_session.commit()
        await postgres_session.refresh(prescription)
        return prescription

    # ── Confirm ──────────────────────────────────────────────────────────

    @with_postgres_session
    async def confirm_prescription(
        self,
        patient_id: str,
        data: ConfirmPrescriptionRequest,
        *,
        postgres_session: AsyncSession,
    ) -> PatientPrescription:
        """Confirm a prescription (draft or new) and create active medications."""
        prescription: PatientPrescription | None = None

        # If confirming an existing draft
        if data.prescription_id:
            result = await postgres_session.execute(
                select(PatientPrescription)
                .where(
                    PatientPrescription.prescription_id == data.prescription_id,
                    PatientPrescription.patient_id == patient_id,
                )
                .options(selectinload(PatientPrescription.medications))
            )
            prescription = result.scalars().first()

            if not prescription:
                from lib.utils.http_exceptions import raise_http_exception
                raise_http_exception(
                    status_code=404,
                    message="Prescription not found",
                )

            if prescription.status == "confirmed":
                logger.warning(
                    "Prescription %s already confirmed for patient %s",
                    data.prescription_id,
                    patient_id,
                )
                return prescription

        if prescription:
            # Update the draft with confirmed data
            prescription.doctor_name = data.doctor_name
            prescription.prescription_date = data.prescription_date
            if data.file_urls:
                prescription.file_urls = data.file_urls
            prescription.status = "confirmed"
            prescription.follow_up_required = data.follow_up_required
            prescription.follow_up_date = data.follow_up_date
            prescription.notes = data.notes
            prescription.extracted_data = None  # clear draft data
            prescription.updated_at = datetime.now().replace(tzinfo=None)
        else:
            # Direct confirm without draft
            prescription = PatientPrescription(
                patient_id=patient_id,
                doctor_name=data.doctor_name,
                prescription_date=data.prescription_date,
                file_urls=data.file_urls,
                status="confirmed",
                follow_up_required=data.follow_up_required,
                follow_up_date=data.follow_up_date,
                notes=data.notes,
            )
            postgres_session.add(prescription)

        await postgres_session.flush()

        for med_data in data.medicines:
            await self._create_medication(
                patient_id=patient_id,
                prescription_id=prescription.prescription_id,
                med_data=med_data,
                session=postgres_session,
            )

        await postgres_session.commit()
        await postgres_session.refresh(
            prescription, attribute_names=["medications"]
        )

        # Vectorize in background — don't block the response
        try:
            await self._sync_qdrant(patient_id, postgres_session)
        except Exception:
            logger.exception("Qdrant sync failed for patient %s", patient_id)

        return prescription

    async def _create_medication(
        self,
        patient_id: str,
        prescription_id: UUID,
        med_data: ConfirmedMedicine,
        session: AsyncSession,
    ) -> PatientMedication:
        """Always create a new medication record. Every prescription = new entry.

        - Same medicine, same everything (renewal): old marked "completed", new created.
          Agent sees the full renewal timeline.
        - Same medicine, something changed (dose/strength): old marked "discontinued",
          new created. Agent can correlate why the change happened.
        - No existing match: created fresh.

        The status difference (completed vs discontinued) tells the agent WHY it ended.
        """
        existing = await self._find_active_by_name(
            patient_id, med_data.name, session
        )
        doses_json = [d.model_dump() for d in med_data.doses]
        now = datetime.now().replace(tzinfo=None)

        for med in existing:
            if self._is_same_medication(med, med_data, doses_json):
                # Renewal — course finished naturally, continued with new prescription
                med.status = "completed"
            else:
                # Something changed — doctor modified the medication
                med.status = "discontinued"
            med.discontinued_at = now

        medication = PatientMedication(
            patient_id=patient_id,
            prescription_id=prescription_id,
            name=med_data.name,
            brand_name=med_data.brand_name,
            strength=med_data.strength,
            formulation=med_data.formulation,
            route=med_data.route,
            food_timing=med_data.food_timing,
            purpose=med_data.purpose,
            instructions=med_data.instructions,
            doses=doses_json,
            start_date=med_data.start_date,
            end_date=med_data.end_date,
            status="as_needed" if med_data.is_sos else "active",
        )
        session.add(medication)
        return medication

    @staticmethod
    def _is_same_medication(
        existing: PatientMedication,
        new: ConfirmedMedicine,
        new_doses_json: list[dict],
    ) -> bool:
        """Check if the medication is essentially the same (renewal, not a change)."""
        if (existing.strength or "").lower().strip() != (new.strength or "").lower().strip():
            return False

        # Compare dose slots + quantities
        existing_doses = sorted(
            [(d.get("slot"), d.get("quantity", 1)) for d in (existing.doses or [])],
        )
        new_doses = sorted(
            [(d.get("slot"), d.get("quantity", 1)) for d in new_doses_json],
        )
        if existing_doses != new_doses:
            return False

        return True

    async def _find_active_by_name(
        self,
        patient_id: str,
        name: str,
        session: AsyncSession,
    ) -> list[PatientMedication]:
        """Find all active medications matching a generic name (case-insensitive)."""
        result = await session.execute(
            select(PatientMedication).where(
                PatientMedication.patient_id == patient_id,
                PatientMedication.status.in_(["active", "as_needed"]),
                PatientMedication.name.ilike(name.strip()),
            )
        )
        return list(result.scalars().all())

    # ── Read operations ──────────────────────────────────────────────────

    @with_postgres_session
    async def get_active_medications(
        self,
        patient_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> list[PatientMedication]:
        result = await postgres_session.execute(
            select(PatientMedication)
            .where(
                PatientMedication.patient_id == patient_id,
                PatientMedication.status.in_(["active", "as_needed"]),
            )
            .order_by(PatientMedication.created_at.desc())
        )
        return list(result.scalars().all())

    @with_postgres_session
    async def get_all_medications(
        self,
        patient_id: str,
        status: str | None = None,
        *,
        postgres_session: AsyncSession,
    ) -> list[PatientMedication]:
        query = select(PatientMedication).where(
            PatientMedication.patient_id == patient_id,
        )
        if status:
            query = query.where(PatientMedication.status == status)
        query = query.order_by(PatientMedication.created_at.desc())
        result = await postgres_session.execute(query)
        return list(result.scalars().all())

    @with_postgres_session
    async def get_medication_list(
        self,
        patient_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> MedicationListResponse:
        """Get medications grouped by status."""
        result = await postgres_session.execute(
            select(PatientMedication)
            .where(PatientMedication.patient_id == patient_id)
            .order_by(PatientMedication.created_at.desc())
        )
        medications = result.scalars().all()

        today = date.today()
        active, as_needed, completed = [], [], []
        for med in medications:
            resp = self.to_response(med, today)
            if med.status == "as_needed":
                as_needed.append(resp)
            elif med.status in ("completed", "discontinued"):
                completed.append(resp)
            else:
                active.append(resp)

        return MedicationListResponse(
            active=active, as_needed=as_needed, completed=completed
        )

    @with_postgres_session
    async def get_patient_prescriptions(
        self,
        patient_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> list[PatientPrescription]:
        result = await postgres_session.execute(
            select(PatientPrescription)
            .where(PatientPrescription.patient_id == patient_id)
            .options(selectinload(PatientPrescription.medications))
            .order_by(PatientPrescription.created_at.desc())
        )
        return list(result.scalars().all())

    @with_postgres_session
    async def get_prescription(
        self,
        prescription_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> PatientPrescription | None:
        result = await postgres_session.execute(
            select(PatientPrescription)
            .where(
                PatientPrescription.prescription_id == prescription_id,
            )
            .options(selectinload(PatientPrescription.medications))
        )
        return result.scalars().first()

    @with_postgres_session
    async def get_medication(
        self,
        medication_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> PatientMedication | None:
        result = await postgres_session.execute(
            select(PatientMedication).where(
                PatientMedication.medication_id == medication_id,
            )
        )
        return result.scalars().first()

    # ── Lifecycle management ─────────────────────────────────────────────

    @with_postgres_session
    async def discontinue_medication(
        self,
        medication_id: str,
        discontinued_by: str,
        *,
        postgres_session: AsyncSession,
    ) -> PatientMedication | None:
        med = await self._get_med(medication_id, postgres_session)
        if not med:
            return None
        med.status = "discontinued"
        med.discontinued_at = datetime.now().replace(tzinfo=None)
        med.discontinued_by = discontinued_by
        await postgres_session.commit()
        await self._sync_qdrant(str(med.patient_id), postgres_session)
        return med

    @with_postgres_session
    async def pause_medication(
        self,
        medication_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> PatientMedication | None:
        med = await self._get_med(medication_id, postgres_session)
        if not med:
            return None
        med.status = "paused"
        await postgres_session.commit()
        await self._sync_qdrant(str(med.patient_id), postgres_session)
        return med

    @with_postgres_session
    async def resume_medication(
        self,
        medication_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> PatientMedication | None:
        med = await self._get_med(medication_id, postgres_session)
        if not med:
            return None
        med.status = "active"
        med.discontinued_at = None
        med.discontinued_by = None
        await postgres_session.commit()
        await self._sync_qdrant(str(med.patient_id), postgres_session)
        return med

    @with_postgres_session
    async def archive_prescription(
        self,
        prescription_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> PatientPrescription | None:
        result = await postgres_session.execute(
            select(PatientPrescription).where(
                PatientPrescription.prescription_id == prescription_id,
            )
        )
        prescription = result.scalars().first()
        if not prescription:
            return None
        prescription.status = "archived"
        await postgres_session.commit()
        return prescription

    @with_postgres_session
    async def complete_expired_medications(
        self,
        *,
        postgres_session: AsyncSession,
    ) -> int:
        """Mark medications past their end_date as completed. Cron target."""
        today = date.today()
        result = await postgres_session.execute(
            select(PatientMedication).where(
                PatientMedication.status == "active",
                PatientMedication.end_date.isnot(None),
                PatientMedication.end_date < today,
            )
        )
        medications = result.scalars().all()
        if not medications:
            return 0

        patient_ids: set[str] = set()
        for med in medications:
            med.status = "completed"
            patient_ids.add(str(med.patient_id))

        await postgres_session.commit()

        for pid in patient_ids:
            try:
                await self._sync_qdrant(pid, postgres_session)
            except Exception:
                logger.exception("Qdrant sync failed for patient %s", pid)

        return len(medications)

    # ── Query helpers (for gamification task generator) ───────────────────

    @with_postgres_session
    async def get_medications_for_date(
        self,
        patient_id: str,
        task_date: date,
        *,
        postgres_session: AsyncSession,
    ) -> list[PatientMedication]:
        """Get active medications valid for a specific date."""
        result = await postgres_session.execute(
            select(PatientMedication).where(
                PatientMedication.patient_id == patient_id,
                PatientMedication.status == "active",
                PatientMedication.start_date <= task_date,
                or_(
                    PatientMedication.end_date.is_(None),
                    PatientMedication.end_date >= task_date,
                ),
            )
        )
        return list(result.scalars().all())

    @with_postgres_session
    async def get_medications_expiring_soon(
        self,
        patient_id: str,
        within_days: int = 3,
        *,
        postgres_session: AsyncSession,
    ) -> list[PatientMedication]:
        """Get active medications expiring within N days."""
        today = date.today()
        target = today + timedelta(days=within_days)
        result = await postgres_session.execute(
            select(PatientMedication).where(
                PatientMedication.patient_id == patient_id,
                PatientMedication.status == "active",
                PatientMedication.end_date.isnot(None),
                PatientMedication.end_date == target,
            )
        )
        return list(result.scalars().all())

    @with_postgres_session
    async def get_follow_up_prescriptions_for_date(
        self,
        patient_id: str,
        task_date: date,
        *,
        postgres_session: AsyncSession,
    ) -> list[PatientPrescription]:
        """Get confirmed prescriptions with follow-up on this date."""
        result = await postgres_session.execute(
            select(PatientPrescription).where(
                PatientPrescription.patient_id == patient_id,
                PatientPrescription.status == "confirmed",
                PatientPrescription.follow_up_required.is_(True),
                PatientPrescription.follow_up_date == task_date,
            )
        )
        return list(result.scalars().all())

    # ── Qdrant sync ──────────────────────────────────────────────────────

    async def _sync_qdrant(
        self, patient_id: str, session: AsyncSession
    ) -> None:
        """Re-vectorize all medications (current + past) for a patient."""
        result = await session.execute(
            select(PatientMedication).where(
                PatientMedication.patient_id == patient_id,
            )
        )
        medications = result.scalars().all()

        if not medications:
            await self.medication_vector_service.delete_medications_vector(
                patient_id
            )
            return

        med_dicts = [
            {
                "name": m.name,
                "brand_name": m.brand_name,
                "strength": m.strength,
                "doses": m.doses,
                "food_timing": m.food_timing,
                "purpose": m.purpose,
                "status": m.status,
                "start_date": str(m.start_date) if m.start_date else None,
                "end_date": str(m.end_date) if m.end_date else None,
            }
            for m in medications
        ]

        # Fetch patient metadata for richer vector context
        patient_result = await session.execute(
            select(Patient).where(Patient.patient_id == patient_id)
        )
        patient = patient_result.scalars().first()
        patient_age = patient.age if patient and hasattr(patient, "age") and patient.age else 0
        patient_gender = patient.gender if patient and patient.gender else "unknown"

        await self.medication_vector_service.upsert_medications_vector(
            patient_id=patient_id,
            medications=med_dicts,
            patient_age=patient_age,
            patient_gender=patient_gender,
        )

    # ── Helpers ──────────────────────────────────────────────────────────

    async def _get_med(
        self, medication_id: str, session: AsyncSession
    ) -> PatientMedication | None:
        result = await session.execute(
            select(PatientMedication).where(
                PatientMedication.medication_id == medication_id,
            )
        )
        return result.scalars().first()

    @staticmethod
    def to_response(med: PatientMedication, today: date) -> MedicationResponse:
        days_remaining = None
        if med.end_date and med.status == "active":
            days_remaining = max(0, (med.end_date - today).days)

        return MedicationResponse(
            medication_id=str(med.medication_id),
            prescription_id=(
                str(med.prescription_id) if med.prescription_id else None
            ),
            name=med.name,
            brand_name=med.brand_name,
            strength=med.strength,
            formulation=med.formulation,
            route=med.route,
            food_timing=med.food_timing,
            purpose=med.purpose,
            instructions=med.instructions,
            doses=med.doses or [],
            start_date=med.start_date,
            end_date=med.end_date,
            status=med.status,
            days_remaining=days_remaining,
            created_at=med.created_at,
        )
