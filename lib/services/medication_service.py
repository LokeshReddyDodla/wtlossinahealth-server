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

# Dose slot → the DailyTask type that tracks whether that slot was logged.
_SLOT_TASK_TYPE = {
    "morning": "TAKE_MEDICATION_MORNING",
    "afternoon": "TAKE_MEDICATION_AFTERNOON",
    "evening": "TAKE_MEDICATION_EVENING",
    "night": "TAKE_MEDICATION_NIGHT",
}


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
                    PatientPrescription.status == "draft",
                    PatientPrescription.file_urls == file_urls,
                )
            )
            existing = result.scalars().first()
            if existing:
                # Update extraction data on existing draft
                existing.extracted_data = extracted_data
                existing.diagnosis = extracted_data.get("diagnosis") or []
                existing.advice = extracted_data.get("advice") or []
                existing.updated_at = datetime.now().replace(tzinfo=None)
                await postgres_session.commit()
                return existing

        prescription = PatientPrescription(
            patient_id=patient_id,
            file_urls=file_urls,
            status="draft",
            diagnosis=extracted_data.get("diagnosis") or [],
            advice=extracted_data.get("advice") or [],
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

            if prescription.status != "draft":
                logger.warning(
                    "Prescription %s is %s, cannot confirm for patient %s",
                    data.prescription_id,
                    prescription.status,
                    patient_id,
                )
                from lib.utils.http_exceptions import raise_http_exception
                raise_http_exception(
                    status_code=400,
                    message=f"Prescription is already {prescription.status}",
                )

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
            prescription.diagnosis = data.diagnosis
            prescription.advice = data.advice
            prescription.extracted_data = None
            prescription.updated_at = datetime.now().replace(tzinfo=None)
        else:
            # Direct confirm without draft
            prescription = PatientPrescription(
                patient_id=patient_id,
                doctor_name=data.doctor_name,
                prescription_date=data.prescription_date,
                file_urls=data.file_urls,
                status="confirmed",
                diagnosis=data.diagnosis,
                advice=data.advice,
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

        # Generate medication tasks for today immediately
        await self._refresh_medication_tasks(UUID(patient_id))

        # Notify patient
        med_names = [m.name for m in data.medicines]
        doctor = data.doctor_name or "Your doctor"
        await self._notify_patient(
            patient_id,
            title="New prescription",
            body=f"{doctor} prescribed: {', '.join(med_names)}",
            event_type="prescription_confirmed",
            prescription_id=str(prescription.prescription_id),
        )

        return prescription

    @with_postgres_session
    async def edit_prescription(
        self,
        patient_id: str,
        prescription_id: str,
        data: ConfirmPrescriptionRequest,
        *,
        postgres_session: AsyncSession,
    ) -> PatientPrescription:
        """Edit a confirmed prescription — replace medications, update metadata.

        All current active/paused/scheduled medications are discontinued, and
        new medications are created from the payload. Completed/discontinued
        medications are left untouched (history preserved).
        """
        from lib.utils.http_exceptions import raise_http_exception

        result = await postgres_session.execute(
            select(PatientPrescription)
            .where(
                PatientPrescription.prescription_id == prescription_id,
                PatientPrescription.patient_id == patient_id,
            )
            .options(selectinload(PatientPrescription.medications))
        )
        prescription = result.scalars().first()

        if not prescription:
            raise_http_exception(
                status_code=404,
                message="Prescription not found",
            )

        if prescription.status != "confirmed":
            raise_http_exception(
                status_code=400,
                message=f"Cannot edit prescription with status {prescription.status}",
            )

        # Update prescription metadata
        prescription.doctor_name = data.doctor_name
        prescription.prescription_date = data.prescription_date
        if data.file_urls:
            prescription.file_urls = data.file_urls
        prescription.follow_up_required = data.follow_up_required
        prescription.follow_up_date = data.follow_up_date
        prescription.notes = data.notes
        prescription.diagnosis = data.diagnosis
        prescription.advice = data.advice
        prescription.updated_at = datetime.now().replace(tzinfo=None)

        # Discontinue all active medications under this prescription
        now = datetime.now().replace(tzinfo=None)
        for med in (prescription.medications or []):
            if med.status in ("active", "paused", "as_needed", "scheduled"):
                med.status = "discontinued"
                med.discontinued_at = now

        await postgres_session.flush()

        # Create new medications from payload
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

        try:
            await self._sync_qdrant(patient_id, postgres_session)
        except Exception:
            logger.exception("Qdrant sync failed for patient %s", patient_id)

        await self._refresh_medication_tasks(UUID(patient_id))

        doctor = data.doctor_name or "Your doctor"
        await self._notify_patient(
            patient_id,
            title="Prescription updated",
            body=f"{doctor} updated your prescription. Check your medication list.",
            event_type="prescription_edited",
            prescription_id=str(prescription.prescription_id),
        )

        return prescription

    async def _load_prescription(self, prescription_id: str, patient_id: str, session: AsyncSession) -> PatientPrescription:
        from lib.utils.http_exceptions import raise_http_exception

        result = await session.execute(
            select(PatientPrescription).where(
                PatientPrescription.prescription_id == prescription_id,
                PatientPrescription.patient_id == patient_id,
            )
        )
        prescription = result.scalars().first()
        if not prescription:
            raise_http_exception(status_code=404, message="Prescription not found")
        return prescription

    @with_postgres_session
    async def store_prescription_document(
        self,
        patient_id: str,
        prescription_id: str,
        file_bytes: bytes,
        file_name: str,
        *,
        postgres_session: AsyncSession,
    ) -> str:
        """Upload the signed PDF and store its URL on the prescription. Called on
        every issue, so the exact signed document is always retrievable."""
        from lib.utils.http_exceptions import raise_http_exception
        from lib.utils.s3_utils import upload_file_to_s3

        prescription = await self._load_prescription(prescription_id, patient_id, postgres_session)
        if prescription.status == "draft":
            raise_http_exception(status_code=400, message="Issue the prescription before storing its document")

        document_url = upload_file_to_s3(
            file_bytes=file_bytes,
            bucket_name="user-assets.aihealth.clinic",
            file_name=file_name,
            content_type="application/pdf",
            folder_path=f"patients/{patient_id}/documents/prescription",
        )
        if not document_url:
            raise_http_exception(status_code=400, message="Failed to upload prescription document")

        prescription.document_url = document_url
        prescription.updated_at = datetime.now().replace(tzinfo=None)
        await postgres_session.commit()
        return document_url

    @with_postgres_session
    async def deliver_prescription(
        self,
        patient_id: str,
        prescription_id: str,
        sender_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> str:
        """Deliver an already-stored prescription document to the patient's chat.
        Falls back to the original upload for prescriptions with no signed PDF."""
        from lib.utils.http_exceptions import raise_http_exception

        prescription = await self._load_prescription(prescription_id, patient_id, postgres_session)
        if prescription.status == "draft":
            raise_http_exception(status_code=400, message="Issue the prescription before sending it")

        document_url = prescription.document_url or (prescription.file_urls[0] if prescription.file_urls else None)
        if not document_url:
            raise_http_exception(status_code=400, message="No document available to send")

        await self._deliver_prescription_chat(
            patient_id=patient_id,
            sender_id=sender_id,
            document_url=document_url,
            doctor_name=prescription.doctor_name or "your doctor",
        )
        return document_url

    @staticmethod
    async def _deliver_prescription_chat(
        patient_id: str, sender_id: str, document_url: str, doctor_name: str
    ) -> None:
        """Post the prescription into the patient↔CP direct chat. Best-effort:
        chat delivery must not fail the send."""
        try:
            from lib.core.container import container
            from lib.schemas.chat_message import ChatMessageCreate, MediaSchema, MetadataSchema
            from lib.services.chat.chat_management_service import ChatManagementService
            from lib.services.chat.chat_messaging_service import ChatMessagingService

            chat_mgmt = container.resolve(ChatManagementService)
            chat_messaging = container.resolve(ChatMessagingService)

            chat_id = await chat_mgmt.find_direct_chat(patient_id, sender_id)
            if not chat_id:
                logger.info("No direct chat for patient %s / sender %s; skipping chat delivery", patient_id, sender_id)
                return

            await chat_messaging.add_message(
                ChatMessageCreate(
                    chat_id=chat_id,
                    sender_id=sender_id,
                    content=f"Your prescription from {doctor_name} is ready.",
                    media=MediaSchema(type="file", url=document_url, caption="Prescription (PDF)"),
                    metadata=MetadataSchema(type="file", status="sent"),
                )
            )
        except Exception:
            logger.exception("Prescription chat delivery failed for patient %s", patient_id)

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
                med.status = "completed"
            else:
                med.status = "discontinued"
            med.discontinued_at = now

        schedule_json = (
            med_data.schedule.model_dump(mode="json") if med_data.schedule else None
        )

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
            schedule=schedule_json,
            start_date=med_data.start_date,
            end_date=med_data.end_date,
            status=self._initial_status(med_data),
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
        # Normalise strength: lowercase + strip *all* whitespace so that
        # "500mg", " 500 MG ", and "500 mg" all compare as equal.
        # Internal whitespace shouldn't trigger a spurious discontinue+create.
        def _normalize_strength(s: str | None) -> str:
            return "".join((s or "").lower().split())

        if _normalize_strength(existing.strength) != _normalize_strength(new.strength):
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

        # Compare schedule
        existing_schedule = existing.schedule or {}
        new_schedule = new.schedule.model_dump(mode="json") if new.schedule else {}
        if existing_schedule != new_schedule:
            return False

        return True

    @staticmethod
    def _initial_status(med_data: ConfirmedMedicine) -> str:
        if med_data.is_sos:
            return "as_needed"
        today = date.today()
        if med_data.end_date and med_data.end_date < today:
            return "completed"
        if med_data.start_date > today:
            return "scheduled"
        return "active"

    async def _find_active_by_name(
        self,
        patient_id: str,
        name: str,
        session: AsyncSession,
    ) -> list[PatientMedication]:
        """Find all active/paused medications matching a generic name (case-insensitive)."""
        result = await session.execute(
            select(PatientMedication).where(
                PatientMedication.patient_id == patient_id,
                PatientMedication.status.in_(["active", "as_needed", "paused"]),
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
        # Dose-logging over the last 14 days. Medication tasks are per time-slot
        # (not per drug), so each med's "% logged" is derived from the slots it's
        # dosed in — honest as "logged", not proof-of-intake.
        slot_stats = await self._slot_logging_stats(patient_id, today, postgres_session)
        active, paused, as_needed, completed = [], [], [], []
        for med in medications:
            resp = self.to_response(med, today)
            resp.adherence_logged_pct, resp.adherence_last_logged_days = (
                self._med_adherence(med, slot_stats, today)
            )
            if med.status == "as_needed":
                as_needed.append(resp)
            elif med.status == "paused":
                paused.append(resp)
            elif med.status in ("completed", "discontinued"):
                completed.append(resp)
            else:  # active, scheduled
                active.append(resp)

        return MedicationListResponse(
            active=active, paused=paused, as_needed=as_needed, completed=completed
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
            .where(
                PatientPrescription.patient_id == patient_id,
                PatientPrescription.status != "archived",
            )
            .options(selectinload(PatientPrescription.medications))
            .order_by(PatientPrescription.created_at.desc())
        )
        return list(result.scalars().all())

    @with_postgres_session
    async def get_prescription(
        self,
        prescription_id: str,
        patient_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> PatientPrescription | None:
        result = await postgres_session.execute(
            select(PatientPrescription)
            .where(
                PatientPrescription.prescription_id == prescription_id,
                PatientPrescription.patient_id == patient_id,
            )
            .options(selectinload(PatientPrescription.medications))
        )
        return result.scalars().first()

    @with_postgres_session
    async def get_medication(
        self,
        medication_id: str,
        patient_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> PatientMedication | None:
        result = await postgres_session.execute(
            select(PatientMedication).where(
                PatientMedication.medication_id == medication_id,
                PatientMedication.patient_id == patient_id,
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
        med_name = med.name
        pid = str(med.patient_id)
        med.status = "discontinued"
        med.discontinued_at = datetime.now().replace(tzinfo=None)
        med.discontinued_by = discontinued_by
        await postgres_session.commit()
        # Best-effort downstream sync — Qdrant outage shouldn't surface
        # a 500 to the caller after the DB commit already succeeded.
        try:
            await self._sync_qdrant(pid, postgres_session)
        except Exception:
            logger.exception("Qdrant sync failed for patient %s", pid)
        await self._refresh_medication_tasks(med.patient_id)
        await self._notify_patient(
            pid, title="Medication discontinued",
            body=f"Your {med_name} has been discontinued by your care team.",
            event_type="medication_discontinued",
        )
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
        med_name = med.name
        pid = str(med.patient_id)
        med.status = "paused"
        await postgres_session.commit()
        try:
            await self._sync_qdrant(pid, postgres_session)
        except Exception:
            logger.exception("Qdrant sync failed for patient %s", pid)
        await self._refresh_medication_tasks(med.patient_id)
        await self._notify_patient(
            pid, title="Medication paused",
            body=f"Your {med_name} has been paused by your care team.",
            event_type="medication_paused",
        )
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
        med_name = med.name
        pid = str(med.patient_id)
        med.status = "active"
        med.discontinued_at = None
        med.discontinued_by = None
        await postgres_session.commit()
        try:
            await self._sync_qdrant(pid, postgres_session)
        except Exception:
            logger.exception("Qdrant sync failed for patient %s", pid)
        await self._refresh_medication_tasks(med.patient_id)
        await self._notify_patient(
            pid, title="Medication resumed",
            body=f"Your {med_name} has been resumed. Check your tasks.",
            event_type="medication_resumed",
        )
        return med

    @with_postgres_session
    async def archive_prescription(
        self,
        prescription_id: str,
        patient_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> PatientPrescription | None:
        result = await postgres_session.execute(
            select(PatientPrescription)
            .where(
                PatientPrescription.prescription_id == prescription_id,
                PatientPrescription.patient_id == patient_id,
            )
            .options(selectinload(PatientPrescription.medications))
        )
        prescription = result.scalars().first()
        if not prescription:
            return None

        prescription.status = "archived"

        # Discontinue all active/paused child medications
        now = datetime.now().replace(tzinfo=None)
        for med in (prescription.medications or []):
            if med.status in ("active", "paused", "as_needed"):
                med.status = "discontinued"
                med.discontinued_at = now

        await postgres_session.commit()

        try:
            await self._sync_qdrant(patient_id, postgres_session)
        except Exception:
            logger.exception("Qdrant sync failed for patient %s", patient_id)

        return prescription

    @with_postgres_session
    async def complete_expired_medications(
        self,
        *,
        postgres_session: AsyncSession,
    ) -> int:
        """Mark medications past their end_date as completed and activate scheduled ones. Cron target."""
        today = date.today()
        changed = 0
        patient_ids: set[str] = set()

        # 1. Complete expired active medications
        result = await postgres_session.execute(
            select(PatientMedication).where(
                PatientMedication.status == "active",
                PatientMedication.end_date.isnot(None),
                PatientMedication.end_date < today,
            )
        )
        for med in result.scalars().all():
            med.status = "completed"
            patient_ids.add(str(med.patient_id))
            changed += 1

        # 2. Activate scheduled medications whose start_date has arrived
        activated_meds: list[tuple[str, str]] = []  # (patient_id, med_name)
        result = await postgres_session.execute(
            select(PatientMedication).where(
                PatientMedication.status == "scheduled",
                PatientMedication.start_date <= today,
            )
        )
        for med in result.scalars().all():
            med.status = "active"
            patient_ids.add(str(med.patient_id))
            activated_meds.append((str(med.patient_id), med.name))
            changed += 1

        if not changed:
            return 0

        await postgres_session.commit()

        for pid in patient_ids:
            try:
                await self._sync_qdrant(pid, postgres_session)
            except Exception:
                logger.exception("Qdrant sync failed for patient %s", pid)

        # Notify patients about newly activated medications
        for pid, med_name in activated_meds:
            await self._notify_patient(
                pid,
                title="Medication starts today",
                body=f"Your {med_name} course begins today. Check your tasks.",
                event_type="medication_activated",
            )

        return changed

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
                "formulation": m.formulation,
                "route": m.route,
                "doses": m.doses,
                "schedule": m.schedule,
                "food_timing": m.food_timing,
                "purpose": m.purpose,
                "instructions": m.instructions,
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

    async def _refresh_medication_tasks(self, patient_id: UUID) -> None:
        """Delete today's pending medication tasks and regenerate from current active meds."""
        try:
            from lib.core.container import container
            from lib.models.gamification import DailyTask
            from lib.services.gamification.task_generator import TaskGeneratorService

            today = date.today()
            med_task_types = [
                "TAKE_MEDICATION_MORNING",
                "TAKE_MEDICATION_AFTERNOON",
                "TAKE_MEDICATION_EVENING",
                "TAKE_MEDICATION_NIGHT",
            ]

            async with self.postgres_store.get_session() as session:
                # Delete only pending (not completed) medication tasks for today
                result = await session.execute(
                    select(DailyTask).where(
                        DailyTask.patient_id == patient_id,
                        DailyTask.task_date == today,
                        DailyTask.task_type.in_(med_task_types),
                        DailyTask.status == "pending",
                    )
                )
                for task in result.scalars().all():
                    await session.delete(task)
                await session.commit()

            # Regenerate — will create fresh tasks based on current active meds
            task_gen = container.resolve(TaskGeneratorService)
            await task_gen.generate_daily_tasks(
                patient_id=patient_id,
                task_date=today,
            )
        except Exception:
            logger.exception("Medication task refresh failed for %s", patient_id)

    @staticmethod
    async def _notify_patient(patient_id: str, title: str, body: str, event_type: str, **extra_data) -> None:
        """Persist a medication-lifecycle inbox row and fire FCM."""
        try:
            from lib.services.notifications import record_and_send_notification

            await record_and_send_notification(
                patient_id,
                category="medication_lifecycle",
                title=title,
                body=body,
                data={"event_type": event_type, **extra_data},
            )
        except Exception:
            logger.debug("Medication notification failed for %s: %s", patient_id, event_type)

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
    async def _slot_logging_stats(patient_id, today: date, session: AsyncSession) -> dict:
        """Per medication-slot dose-logging over the last 14 days:
        {task_type: {done, total, last: date}}."""
        from lib.models.gamification import DailyTask

        since = today - timedelta(days=14)
        rows = (
            await session.execute(
                select(DailyTask.task_type, DailyTask.status, DailyTask.task_date).where(
                    DailyTask.patient_id == patient_id,
                    DailyTask.task_type.in_(list(_SLOT_TASK_TYPE.values())),
                    DailyTask.task_date >= since,
                )
            )
        ).all()
        stats: dict = {}
        for ttype, status, tdate in rows:
            s = stats.setdefault(ttype, {"done": 0, "total": 0, "last": None})
            s["total"] += 1
            if status == "completed":
                s["done"] += 1
                if s["last"] is None or tdate > s["last"]:
                    s["last"] = tdate
        return stats

    @staticmethod
    def _med_adherence(med: PatientMedication, slot_stats: dict, today: date):
        """(logged_pct, days_since_last_logged) from the slots this med is dosed in."""
        slots = {d.get("slot") for d in (med.doses or []) if isinstance(d, dict) and d.get("slot")}
        ttypes = [_SLOT_TASK_TYPE[s] for s in slots if s in _SLOT_TASK_TYPE]
        total = sum(slot_stats.get(t, {}).get("total", 0) for t in ttypes)
        if total == 0:
            return None, None
        done = sum(slot_stats.get(t, {}).get("done", 0) for t in ttypes)
        lasts = [slot_stats[t]["last"] for t in ttypes if slot_stats.get(t, {}).get("last")]
        last_days = (today - max(lasts)).days if lasts else None
        return round(100 * done / total), last_days

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
            schedule=med.schedule,
            start_date=med.start_date,
            end_date=med.end_date,
            is_sos=med.status == "as_needed",
            status=med.status,
            days_remaining=days_remaining,
            created_at=med.created_at,
        )
