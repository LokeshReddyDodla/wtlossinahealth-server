"""Manual derived-data controls — the generic "fix this patient" primitives.

Every targeted repair is one of two moves: mark the changed days dirty (the
drain regenerates reports, rollups, vectors, and the panel through its normal
path) or kick the drain directly (finalizers-only when nothing is dirty).
Roster-wide repair is the coverage sweep's job, not these.
"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import Depends, Query
from pydantic import BaseModel, Field

from lib.dependencies.auth.admin_auth import get_current_admin
from lib.derived import DataDomain, dates_between, enqueue_refresh_patient, mark_dirty
from lib.derived.dirty import _refresh_job_id
from lib.models.admin import Admin
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router

_MAX_PATIENTS = 100
_MAX_RANGE_DAYS = 366


class MarkDirtyRequest(BaseModel):
    patient_ids: list[str] = Field(..., min_length=1, max_length=_MAX_PATIENTS)
    domains: list[DataDomain] = Field(
        default_factory=lambda: list(DataDomain),
        description="Defaults to every domain.",
    )
    start_date: date
    end_date: date


@router.post("/mark-dirty", response_model=SuccessResponse)
async def mark_dirty_range(
    body: MarkDirtyRequest,
    current_admin: Admin = Depends(get_current_admin),
) -> SuccessResponse:
    """Regenerate everything derived from these patients' data in the range."""
    if body.end_date < body.start_date:
        raise_http_exception(status_code=400, message="end_date before start_date")
    if (body.end_date - body.start_date).days > _MAX_RANGE_DAYS:
        raise_http_exception(
            status_code=400, message=f"Range capped at {_MAX_RANGE_DAYS} days"
        )

    days = dates_between(body.start_date, body.end_date, cap_days=_MAX_RANGE_DAYS)
    for patient_id in body.patient_ids:
        for domain in body.domains:
            await mark_dirty(patient_id, domain, days, defer_s=0)

    return SuccessResponse(
        message=(
            f"Marked {len(days)} days × {len(body.domains)} domains dirty "
            f"for {len(body.patient_ids)} patients"
        ),
        data={"refresh_job_ids": [_refresh_job_id(p) for p in body.patient_ids]},
    )


@router.post("/refresh-patient/{patient_id}", response_model=SuccessResponse)
async def refresh_patient_now(
    patient_id: str,
    current_admin: Admin = Depends(get_current_admin),
) -> SuccessResponse:
    """Kick the drain for one patient immediately — drains any dirty cells and
    recomputes the panel row even when nothing is dirty."""
    await enqueue_refresh_patient(patient_id)
    return SuccessResponse(
        message="Refresh queued",
        data={"job_id": _refresh_job_id(patient_id)},
    )
