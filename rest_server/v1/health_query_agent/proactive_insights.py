"""
Proactive Insights — history and feedback endpoints.

GET  /health-query-agent/proactive-insights?patient_id=...&limit=20
POST /health-query-agent/proactive-insights/feedback
"""

from typing import Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

from lib.core.constants import ProfileTypeEnum
from lib.core.container import container
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import get_care_provider_access_service
from lib.services.care_provider_access_service import CareProviderAccessService
from rest_server.response_models import SuccessResponse

from .router import router


# ---------------------------------------------------------------------------
# History — "Your health insights this week"
# ---------------------------------------------------------------------------


class InsightHistoryItem(BaseModel):
    insight_id: str | None = None
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
    # Access control: patients can only see their own, care providers only assigned patients
    await _verify_patient_access(current_actor, patient_id, care_provider_access_service)

    from lib.ai_foundation.agents.proactive_monitor.insight_tracker import InsightTracker

    tracker: InsightTracker = container.resolve(InsightTracker)
    docs = await tracker.get_history(patient_id, limit=limit)

    items = [
        InsightHistoryItem(
            insight_id=doc.get("insight_id"),
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
):
    """Submit feedback on a proactive insight.

    Logs to Langfuse as a score for quality tracking.
    """
    from lib.ai_foundation.models.gateway import ModelGateway

    recorded = False
    try:
        gateway: ModelGateway = container.resolve(ModelGateway)
        gateway.log_score(
            trace_id=payload.insight_id,
            name="insight_feedback",
            value=1.0 if payload.thumbs_up else 0.0,
            comment=payload.comment,
        )
        recorded = True
    except Exception:
        pass  # Langfuse scoring is best-effort

    return SuccessResponse(
        message="Feedback recorded" if recorded else "Feedback noted",
        data=InsightFeedbackResponse(recorded=recorded, insight_id=payload.insight_id),
    )


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


async def _verify_patient_access(
    actor: Actor,
    patient_id: str,
    access_service: CareProviderAccessService,
) -> None:
    """Verify the actor can access this patient's data."""
    if actor.role == ProfileTypeEnum.ADMIN:
        return  # Admins can access anyone

    if actor.role == ProfileTypeEnum.PATIENT:
        if actor.id != patient_id:
            raise HTTPException(status_code=403, detail="Patients can only access their own insights")
        return

    if actor.role == ProfileTypeEnum.CARE_PROVIDER:
        from uuid import UUID
        accessible = await access_service.get_accessible_patients(
            care_provider_id=UUID(actor.id),
            patient_ids=[UUID(patient_id)],
        )
        if not accessible:
            raise HTTPException(status_code=403, detail="You don't have access to this patient's insights")
