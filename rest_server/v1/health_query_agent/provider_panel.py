"""
Provider Panel — ranked view of patients needing attention.

GET /health-query-agent/provider-panel

Returns patients ranked by health urgency based on recent proactive
monitor insights. Fast (<200ms) — queries stored insights, no live scans.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import Depends, Query
from pydantic import BaseModel, Field

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import get_care_provider_access_service
from lib.services.care_provider_access_service import CareProviderAccessService
from rest_server.response_models import SuccessResponse

from .router import router

logger = logging.getLogger(__name__)


# ── Request / Response models ────────────────────────────────────────────


class ProviderPanelRequest(BaseModel):
    patient_ids: list[str] = Field(description="Patient IDs to include in the panel")


# ── Endpoint ─────────────────────────────────────────────────────────────


@router.post(
    "/provider-panel",
    response_model=SuccessResponse,
    summary="Get provider's patient panel ranked by health urgency",
)
async def get_provider_panel(
    payload: ProviderPanelRequest,
    limit: int = Query(20, ge=1, le=50),
    days: int = Query(7, ge=1, le=30),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.CARE_PROVIDER, ProfileTypeEnum.ADMIN],
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Ranked list of patients needing attention based on recent health insights.

    Uses stored proactive monitor insights (updated 4x/day). No live scans —
    response time <200ms.

    - Care providers: must provide their assigned patient IDs
    - Admins: can query any patient IDs
    """
    import time
    start = time.perf_counter()

    # Access control
    if current_actor.role == ProfileTypeEnum.CARE_PROVIDER:
        try:
            patient_uuids = [UUID(pid) for pid in payload.patient_ids]
        except (ValueError, TypeError):
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Invalid patient ID format — expected UUID")
        accessible = await care_provider_access_service.get_accessible_patients(
            care_provider_id=UUID(current_actor.id),
            patient_ids=patient_uuids,
        )
        patient_ids = [str(pid) for pid in accessible]
    else:
        # Admin — all requested patients
        patient_ids = payload.patient_ids

    if not patient_ids:
        from lib.ai_foundation.agents.health_query.triage import ProviderPanelResponse
        return SuccessResponse(
            message="No patients to scan",
            data=ProviderPanelResponse(total_patients=0, patients_needing_attention=0).model_dump(),
        )

    # Resolve patient names
    from lib.core.container import container
    from lib.ai_foundation.agents.health_query.patient_resolver import PatientNameResolver

    resolver: PatientNameResolver = container.resolve(PatientNameResolver)
    names = await resolver.resolve_names(patient_ids)

    # Query recent insights
    from lib.ai_foundation.agents.proactive_monitor.insight_tracker import InsightTracker

    tracker: InsightTracker = container.resolve(InsightTracker)
    insights_by_patient = await tracker.get_insights_for_patients(
        patient_ids, since_days=days, limit_per_patient=5,
    )

    # Rank patients
    from lib.ai_foundation.agents.health_query.triage import rank_patients, build_panel_response

    ranked = rank_patients(
        patient_ids=patient_ids,
        patient_names=names,
        insights_by_patient=insights_by_patient,
    )

    response = build_panel_response(
        total_patients=len(patient_ids),
        ranked_patients=ranked,
        limit=limit,
    )

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    logger.info("Provider panel: %d patients, %d needing attention, %dms",
                len(patient_ids), response.patients_needing_attention, elapsed_ms)

    return SuccessResponse(
        message="Provider panel loaded",
        data=response.model_dump(mode="json"),
    )
