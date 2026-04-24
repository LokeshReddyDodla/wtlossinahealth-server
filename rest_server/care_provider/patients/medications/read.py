"""Care provider medication endpoints — view patient's medication data."""

from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import Depends, Query
from pydantic import BaseModel

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_adr_checker,
    get_medication_service,
    get_medication_side_effects_service,
    get_prescription_differ,
)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.medication import MedicationScheduleResponse, RefillAlert
from lib.services.medication.adr_checker import ADRChecker
from lib.services.medication.prescription_differ import PrescriptionDiffer
from lib.services.medication.service import MedicationService
from lib.services.medication.side_effects_service import MedicationSideEffectsService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/schedules", response_model=SuccessResponse)
async def get_patient_schedules(
    patient_id: UUID,
    medication_service: MedicationService = Depends(get_medication_service),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.READ,
            feature=CareProviderFeature.REPORTS,
        )
    ),
):
    """Get patient's active medication schedules."""
    schedules = await medication_service.get_active_schedules(patient_id)
    today = date.today()
    data = []
    for s in schedules:
        resp = MedicationScheduleResponse.model_validate(s)
        if s.end_date:
            resp.days_remaining = max(0, (s.end_date - today).days)
        data.append(resp)
    return SuccessResponse(message="Patient medication schedules", data=data)


@router.get("/adherence", response_model=SuccessResponse)
async def get_patient_adherence(
    patient_id: UUID,
    days: int = Query(30, ge=1, le=365),
    medication_service: MedicationService = Depends(get_medication_service),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.READ,
            feature=CareProviderFeature.REPORTS,
        )
    ),
):
    """Get patient's medication adherence summary."""
    from sqlalchemy import func, select
    from lib.core.container import container
    from lib.core.postgres_store import PostgresStore
    from lib.models.medication_schedule import MedicationDoseSlot, MedicationSchedule
    from datetime import timedelta

    store = container.resolve(PostgresStore)
    cutoff = date.today() - timedelta(days=days)

    async with store.get_session() as session:
        result = await session.execute(
            select(
                MedicationDoseSlot.schedule_id,
                MedicationDoseSlot.status,
                func.count(MedicationDoseSlot.slot_id),
            )
            .where(
                MedicationDoseSlot.patient_id == patient_id,
                MedicationDoseSlot.slot_date >= cutoff,
            )
            .group_by(MedicationDoseSlot.schedule_id, MedicationDoseSlot.status)
        )
        rows = result.all()

    # Aggregate
    schedule_stats = {}
    for schedule_id, status_val, count in rows:
        if schedule_id not in schedule_stats:
            schedule_stats[schedule_id] = {"taken": 0, "missed": 0, "skipped": 0, "pending": 0}
        schedule_stats[schedule_id][status_val] = count

    # Get schedule names
    schedules = await medication_service.get_active_schedules(patient_id)
    schedule_map = {s.schedule_id: s for s in schedules}

    per_medication = []
    total_taken = total_missed = total_skipped = total_slots = 0
    for sid, stats in schedule_stats.items():
        taken = stats.get("taken", 0)
        missed = stats.get("missed", 0)
        skipped = stats.get("skipped", 0)
        total = taken + missed + skipped + stats.get("pending", 0)
        adherence = (taken / total * 100) if total > 0 else 0

        sched = schedule_map.get(sid)
        per_medication.append({
            "schedule_id": str(sid),
            "brand_name": sched.brand_name if sched else None,
            "generic_name": sched.generic_name if sched else None,
            "adherence_pct": round(adherence, 1),
            "total_slots": total,
            "taken": taken,
            "missed": missed,
            "skipped": skipped,
        })
        total_taken += taken
        total_missed += missed
        total_skipped += skipped
        total_slots += total

    overall = (total_taken / total_slots * 100) if total_slots > 0 else 0

    return SuccessResponse(
        message="Adherence summary",
        data={
            "period_days": days,
            "overall_adherence_pct": round(overall, 1),
            "total_slots": total_slots,
            "taken": total_taken,
            "missed": total_missed,
            "skipped": total_skipped,
            "per_medication": per_medication,
        },
    )


@router.get("/missed-doses", response_model=SuccessResponse)
async def get_missed_doses(
    patient_id: UUID,
    days: int = Query(7, ge=1, le=90),
    medication_service: MedicationService = Depends(get_medication_service),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.READ,
            feature=CareProviderFeature.REPORTS,
        )
    ),
):
    """Get missed dose log for a patient."""
    from datetime import timedelta
    from sqlalchemy import select
    from lib.core.container import container
    from lib.core.postgres_store import PostgresStore
    from lib.models.medication_schedule import MedicationDoseSlot, MedicationSchedule

    store = container.resolve(PostgresStore)
    cutoff = date.today() - timedelta(days=days)

    async with store.get_session() as session:
        result = await session.execute(
            select(MedicationDoseSlot, MedicationSchedule)
            .join(MedicationSchedule)
            .where(
                MedicationDoseSlot.patient_id == patient_id,
                MedicationDoseSlot.slot_date >= cutoff,
                MedicationDoseSlot.status.in_(["missed", "skipped"]),
            )
            .order_by(MedicationDoseSlot.slot_date.desc(), MedicationDoseSlot.slot_time)
        )
        rows = result.all()

    data = [
        {
            "slot_date": str(slot.slot_date),
            "slot_time": slot.slot_time,
            "slot_label": slot.slot_label,
            "status": slot.status,
            "skipped_reason": slot.skipped_reason,
            "brand_name": sched.brand_name,
            "generic_name": sched.generic_name,
            "strength": sched.strength,
        }
        for slot, sched in rows
    ]
    return SuccessResponse(message="Missed doses fetched", data=data)


@router.get("/side-effects", response_model=SuccessResponse)
async def get_patient_side_effects(
    patient_id: UUID,
    days: int = Query(30, ge=1, le=365),
    side_effects_service: MedicationSideEffectsService = Depends(
        get_medication_side_effects_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.READ,
            feature=CareProviderFeature.REPORTS,
        )
    ),
):
    """Get side effect reports for a patient."""
    effects = await side_effects_service.get_side_effects(
        patient_id=patient_id, days_back=days
    )
    return SuccessResponse(message="Side effects fetched", data=effects)


@router.get("/allergies", response_model=SuccessResponse)
async def get_patient_allergies(
    patient_id: UUID,
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.READ,
            feature=CareProviderFeature.REPORTS,
        )
    ),
):
    """Get patient's drug allergy registry."""
    from sqlalchemy import select
    from lib.core.container import container
    from lib.core.postgres_store import PostgresStore
    from lib.models.patient_drug_allergy import PatientDrugAllergy

    store = container.resolve(PostgresStore)
    async with store.get_session() as session:
        result = await session.execute(
            select(PatientDrugAllergy).where(
                PatientDrugAllergy.patient_id == patient_id,
                PatientDrugAllergy.is_active == True,
            )
        )
        allergies = result.scalars().all()

    from lib.schemas.patient_drug_allergy import PatientDrugAllergy as AllergySchema
    data = [AllergySchema.model_validate(a) for a in allergies]
    return SuccessResponse(message="Drug allergies fetched", data=data)


class AddAllergyRequest(BaseModel):
    allergy_name: str
    reaction_type: Optional[str] = "ADR"
    severity: Optional[str] = None
    notes: Optional[str] = None


@router.post("/allergies", response_model=SuccessResponse)
async def add_patient_allergy(
    patient_id: UUID,
    payload: AddAllergyRequest,
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.CREATE,
            feature=CareProviderFeature.REPORTS,
        )
    ),
):
    """Add a drug allergy to the patient's registry."""
    from datetime import date as date_type
    from sqlalchemy import select
    from lib.core.container import container
    from lib.core.postgres_store import PostgresStore
    from lib.models.patient_drug_allergy import PatientDrugAllergy

    store = container.resolve(PostgresStore)
    async with store.get_session() as session:
        # Check if already exists
        existing = await session.execute(
            select(PatientDrugAllergy).where(
                PatientDrugAllergy.patient_id == patient_id,
                PatientDrugAllergy.allergy_name == payload.allergy_name,
                PatientDrugAllergy.is_active == True,
            )
        )
        if existing.scalars().first():
            return SuccessResponse(message="Allergy already exists", data=None)

        allergy = PatientDrugAllergy(
            patient_id=patient_id,
            allergy_name=payload.allergy_name,
            reaction_type=payload.reaction_type,
            severity=payload.severity,
            source="care_provider",
            reported_date=date_type.today(),
            notes=payload.notes,
            is_active=True,
        )
        session.add(allergy)
        await session.commit()

    return SuccessResponse(message="Drug allergy added", data=None)


@router.get("/diff", response_model=SuccessResponse)
async def get_prescription_diff(
    patient_id: UUID,
    prescription_differ: PrescriptionDiffer = Depends(get_prescription_differ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.READ,
            feature=CareProviderFeature.REPORTS,
        )
    ),
):
    """Get prescription diff — compare active meds against latest prescription.

    Call this endpoint after extracting a new prescription but before confirming,
    passing the extracted medicines as query context.
    """
    # For now, return the current active medication state
    # The diff is typically called with new_medicines from the frontend
    from lib.services.medication.service import MedicationService
    from lib.dependencies.service_dependencies import get_medication_service

    medication_service = get_medication_service()
    schedules = await medication_service.get_active_schedules(patient_id)

    data = [
        {
            "schedule_id": str(s.schedule_id),
            "brand_name": s.brand_name,
            "generic_name": s.generic_name,
            "strength": s.strength,
            "frequency_raw": s.frequency_raw,
            "schedule_type": s.schedule_type,
            "status": s.status,
        }
        for s in schedules
    ]
    return SuccessResponse(
        message="Current active medications for diffing",
        data=data,
    )


class InteractionCheckRequest(BaseModel):
    """Medicines to check for interactions (from a new prescription preview)."""
    medicines: list


@router.post("/check-interactions", response_model=SuccessResponse)
async def check_drug_interactions(
    patient_id: UUID,
    payload: InteractionCheckRequest,
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.READ,
            feature=CareProviderFeature.REPORTS,
        )
    ),
):
    """Check new medicines for drug interactions before confirming a prescription.

    Checks: duplicate ingredients, ADR conflicts, AI drug-drug interactions.
    """
    from lib.core.container import container
    from lib.services.medication.interaction_checker import DrugInteractionChecker

    checker = container.resolve(DrugInteractionChecker)
    result = await checker.check_interactions(
        patient_id=patient_id,
        new_medicines=payload.medicines,
    )
    return SuccessResponse(
        message="Interaction check complete",
        data=result.model_dump(),
    )
