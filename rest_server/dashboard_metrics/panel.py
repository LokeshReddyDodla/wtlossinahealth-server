"""Cross-patient panel read — the enriched roster / triage worklist.

Serves the materialized patient_panel_signal rows in one scoped, paginated,
server-side sorted/filtered query — no per-patient AI, no fan-out. Provider-gated
and facility/CP-scoped exactly like the other dashboard-metrics roster reads.
"""

from fastapi import Depends, HTTPException, Query, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import get_patient_panel_service
from lib.services.patient_panel.service import PatientPanelService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from rest_server.response_models import SuccessResponse

from .read import resolve_patient_scope
from .router import router


@router.get("/patients/panel", response_model=SuccessResponse)
async def get_patient_panel(
    status_filter: str | None = Query(None, alias="status"),
    actionable: bool = Query(False),
    modality: str | None = Query(None),
    search: str | None = Query(None),
    needs_review: bool | None = Query(None),
    sort: str = Query("priority"),
    order: str = Query("asc"),
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=200),
    panel_service: PatientPanelService = Depends(get_patient_panel_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.CARE_PROVIDER, ProfileTypeEnum.ADMIN],
            care_provider_action=CareProviderPermissionAction.READ,
            care_provider_feature=CareProviderFeature.HEALTH_FACILITY,
        )
    ),
):
    facility_id, care_provider_id, is_facility_admin = resolve_patient_scope(
        current_actor.model
    )
    rows, total = await panel_service.list_panel(
        facility_id=facility_id,
        care_provider_id=care_provider_id,
        is_facility_admin=is_facility_admin,
        status=status_filter,
        actionable=actionable,
        modality=modality,
        search=search,
        needs_review=needs_review,
        sort=sort,
        order=1 if order == "asc" else -1,
        skip=(page - 1) * size,
        limit=size,
    )
    return SuccessResponse(
        message=f"{total} patients",
        data={"items": rows, "total": total, "page": page, "size": size},
    )


@router.post("/patients/{patient_id}/panel/reviewed", response_model=SuccessResponse)
async def mark_panel_reviewed(
    patient_id: str,
    state_since: str | None = Query(
        None, description="The state_since the reviewer saw; the review only lands if it still matches."
    ),
    panel_service: PatientPanelService = Depends(get_patient_panel_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.CARE_PROVIDER, ProfileTypeEnum.ADMIN],
            care_provider_action=CareProviderPermissionAction.UPDATE,
            care_provider_feature=CareProviderFeature.HEALTH_FACILITY,
        )
    ),
):
    outcome = await panel_service.mark_reviewed(patient_id, state_since)
    if outcome == "not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not on panel")
    if outcome == "stale":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Patient state changed since it was viewed; refresh before reviewing.",
        )
    return SuccessResponse(message="Marked reviewed")
