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

    @with_postgres_session
    async def create_prescription_with_medications(
        self,
        patient_id: str,
        data: ConfirmPrescriptionRequest,
        *,
        postgres_session: AsyncSession,
    ) -> PatientPrescription:
        """Save confirmed prescription and create/update active medications."""
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
            await self._upsert_medication(
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

    async def _upsert_medication(
        self,
        patient_id: str,
        prescription_id: UUID,
        med_data: ConfirmedMedicine,
        session: AsyncSession,
    ) -> PatientMedication:
        """Create or update an active medication.

        Dedup: same name (case-insensitive) + strength → update existing.
        """
        existing = await self._find_active_medication(
            patient_id, med_data.name, med_data.strength, session
        )

        doses_json = [d.model_dump() for d in med_data.doses]

        if existing:
            existing.prescription_id = prescription_id
            existing.brand_name = med_data.brand_name
            existing.strength = med_data.strength
            existing.formulation = med_data.formulation
            existing.route = med_data.route
            existing.food_timing = med_data.food_timing
            existing.purpose = med_data.purpose
            existing.instructions = med_data.instructions
            existing.doses = doses_json
            existing.start_date = med_data.start_date
            existing.end_date = med_data.end_date
            existing.status = "as_needed" if med_data.is_sos else "active"
            existing.updated_at = datetime.now().replace(tzinfo=None)
            return existing

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

    async def _find_active_medication(
        self,
        patient_id: str,
        name: str,
        strength: str | None,
        session: AsyncSession,
    ) -> PatientMedication | None:
        """Find existing active medication by name + strength."""
        query = select(PatientMedication).where(
            PatientMedication.patient_id == patient_id,
            PatientMedication.status.in_(["active", "as_needed"]),
            PatientMedication.name.ilike(name.strip()),
        )
        if strength:
            query = query.where(
                PatientMedication.strength.ilike(strength.strip())
            )
        result = await session.execute(query)
        return result.scalars().first()

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
