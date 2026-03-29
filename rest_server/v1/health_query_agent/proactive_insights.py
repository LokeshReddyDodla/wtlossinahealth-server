"""
Proactive Insights — history and feedback endpoints.

GET  /health-query-agent/proactive-insights?patient_id=...&limit=20
POST /health-query-agent/proactive-insights/feedback
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

from lib.core.constants import ProfileTypeEnum
from lib.core.container import container
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import get_care_provider_access_service
from lib.services.care_provider_access_service import CareProviderAccessService
from rest_server.response_models import SuccessResponse

from .router import router


def _parse_patient_uuid(patient_id: str) -> UUID:
    try:
        return UUID(patient_id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid patient ID format — expected UUID") from exc


# ---------------------------------------------------------------------------
# History — "Your health insights this week"
# ---------------------------------------------------------------------------


class InsightHistoryItem(BaseModel):
    insight_id: str | None = None
    trace_id: str | None = None
    category: str
    severity: str
    title: str | None = None
    message: str
    suggested_query: str | None = None
    created_at: str


@router.get("/proactive-insights", response_model=SuccessResponse[list[InsightHistoryItem]])
async def get_insight_history(
    patient_id: str = Query(..., description="Patient ID to fetch insights for"),
    limit: int = Query(20, ge=1, le=100, description="Max insights to return"),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER, ProfileTypeEnum.ADMIN],
            check_permissions=False,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Get recent proactive insight history for a patient.

    Returns insights newest-first. Patients see their own insights,
    care providers see their assigned patients' insights.
    """
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=_parse_patient_uuid(patient_id),
        care_provider_access_service=care_provider_access_service,
    )

    from lib.ai_foundation.agents.proactive_monitor.insight_tracker import InsightTracker

    tracker: InsightTracker = container.resolve(InsightTracker)
    docs = await tracker.get_history(str(verified_pid), limit=limit)

    items = [
        InsightHistoryItem(
            insight_id=doc.get("insight_id"),
            trace_id=doc.get("trace_id"),
            category=doc.get("category", ""),
            severity=doc.get("severity", ""),
            title=doc.get("title"),
            message=doc.get("message", ""),
            suggested_query=doc.get("suggested_query"),
            created_at=str(doc.get("created_at", "")),
        )
        for doc in docs
    ]

    return SuccessResponse(
        message=f"{len(items)} insights found",
        data=items,
    )


# ---------------------------------------------------------------------------
# Feedback — thumbs up/down on an insight
# ---------------------------------------------------------------------------


class InsightFeedbackRequest(BaseModel):
    insight_id: str = Field(..., description="The insight_id from the notification data payload")
    thumbs_up: bool = Field(..., description="True = helpful, False = not helpful")
    comment: Optional[str] = Field(None, max_length=500, description="Optional comment")


class InsightFeedbackResponse(BaseModel):
    recorded: bool
    insight_id: str


@router.post("/proactive-insights/feedback", response_model=SuccessResponse[InsightFeedbackResponse])
async def submit_insight_feedback(
    payload: InsightFeedbackRequest,
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER, ProfileTypeEnum.ADMIN],
            check_permissions=False,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Submit feedback on a proactive insight.

    Logs to Langfuse as a score for quality tracking.
    """
    from lib.ai_foundation.agents.proactive_monitor.insight_tracker import InsightTracker
    from lib.ai_foundation.models.gateway import ModelGateway

    recorded = False
    try:
        tracker: InsightTracker = container.resolve(InsightTracker)
        doc = await tracker.get_by_insight_id(payload.insight_id)
        if not doc or not doc.get("patient_id"):
            raise HTTPException(status_code=404, detail="Insight not found")
        await resolve_patient_access(
            actor=current_actor,
            patient_id=_parse_patient_uuid(str(doc["patient_id"])),
            care_provider_access_service=care_provider_access_service,
        )
        trace_id = doc.get("trace_id") if doc else None
        if not trace_id:
            raise ValueError("No trace_id found for insight feedback")
        gateway: ModelGateway = container.resolve(ModelGateway)
        gateway.log_score(
            trace_id=trace_id,
            name="insight_feedback",
            value=1.0 if payload.thumbs_up else 0.0,
            comment=payload.comment,
        )
        recorded = True
    except HTTPException:
        raise
    except Exception as exc:
        logging.getLogger(__name__).warning("Insight feedback failed for %s: %s", payload.insight_id, exc)

    return SuccessResponse(
        message="Feedback recorded" if recorded else "Feedback noted",
        data=InsightFeedbackResponse(recorded=recorded, insight_id=payload.insight_id),
    )
