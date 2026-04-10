"""GET /medications/{patient_id}/adherence — adherence summary.
PATCH /medications/{patient_id}/dose-log/{log_id} — update a dose log entry.
"""

from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import Depends, Query, status
from pydantic import BaseModel

from lib.core.constants import ProfileTypeEnum
from lib.core.postgres_store import PostgresStore
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
)
from lib.models.medication_dose_log import MedicationDoseLog
from lib.models.patient_medication import PatientMedication
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from sqlalchemy import cast, Date, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from lib.dependencies.database import get_postgres_session

from .router import router


class UpdateDoseLogRequest(BaseModel):
    status: str  # taken / missed / skipped
    notes: str | None = None


@router.get(
    "/{patient_id}/adherence",
    response_model=SuccessResponse,
)
async def get_adherence(
    patient_id: str,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    session: AsyncSession = Depends(get_postgres_session),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.PATIENT,
            ],
            care_provider_feature=CareProviderFeature.REPORTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Per-medication adherence summary for a date range."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )
    pid = str(verified_pid)

    end = end_date or date.today()
    start = start_date or date(end.year, end.month, 1)

    # Get dose logs grouped by medication
    result = await session.execute(
        select(
            MedicationDoseLog.medication_id,
            MedicationDoseLog.status,
            func.count().label("count"),
        )
        .where(
            MedicationDoseLog.patient_id == pid,
            MedicationDoseLog.log_date >= start,
            MedicationDoseLog.log_date <= end,
        )
        .group_by(MedicationDoseLog.medication_id, MedicationDoseLog.status)
    )
    rows = result.all()

    # Build per-medication summary
    med_stats: dict[str, dict[str, int]] = {}
    for row in rows:
        mid = str(row.medication_id)
        med_stats.setdefault(mid, {"taken": 0, "missed": 0, "skipped": 0})
        if row.status in med_stats[mid]:
            med_stats[mid][row.status] = row.count

    # Get medication names
    med_ids = list(med_stats.keys())
    if med_ids:
        med_result = await session.execute(
            select(PatientMedication).where(
                PatientMedication.medication_id.in_(med_ids)
            )
        )
        med_names = {
            str(m.medication_id): m.name for m in med_result.scalars().all()
        }
    else:
        med_names = {}

    data = []
    for mid, stats in med_stats.items():
        total = stats["taken"] + stats["missed"] + stats["skipped"]
        data.append({
            "medication_id": mid,
            "medication_name": med_names.get(mid, "Unknown"),
            "taken": stats["taken"],
            "missed": stats["missed"],
            "skipped": stats["skipped"],
            "total": total,
            "adherence_rate": round(stats["taken"] / total, 2) if total else 0,
        })

    return SuccessResponse(
        message="Adherence summary retrieved",
        data={"start_date": str(start), "end_date": str(end), "medications": data},
    )


@router.patch(
    "/{patient_id}/dose-log/{log_id}",
    response_model=SuccessResponse,
)
async def update_dose_log(
    patient_id: str,
    log_id: str,
    payload: UpdateDoseLogRequest,
    session: AsyncSession = Depends(get_postgres_session),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.PATIENT,
            ],
            care_provider_feature=CareProviderFeature.REPORTS,
            care_provider_action=CareProviderPermissionAction.UPDATE,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Update a specific dose log entry (e.g., mark as skipped)."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )

    result = await session.execute(
        select(MedicationDoseLog).where(
            MedicationDoseLog.dose_log_id == log_id,
            MedicationDoseLog.patient_id == str(verified_pid),
        )
    )
    log_entry = result.scalars().first()
    if not log_entry:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND,
            message="Dose log entry not found",
        )

    if payload.status not in ("taken", "missed", "skipped"):
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Status must be one of: taken, missed, skipped",
        )

    log_entry.status = payload.status
    if payload.notes is not None:
        log_entry.notes = payload.notes
    if payload.status != "taken":
        log_entry.taken_at = None

    await session.commit()

    return SuccessResponse(
        message="Dose log updated",
        data={"dose_log_id": str(log_entry.dose_log_id), "status": log_entry.status},
    )
