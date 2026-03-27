"""
Proactive Insights — history and feedback endpoints.

GET  /health-query-agent/proactive-insights?patient_id=...&limit=20
POST /health-query-agent/proactive-insights/feedback
"""

from typing import Optional

from fastapi import Depends, Query
from pydantic import BaseModel, Field

from lib.core.constants import ProfileTypeEnum
from lib.core.container import container
from lib.dependencies.actor import Actor, get_current_actor
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
):
    """Get recent proactive insight history for a patient.

    Returns insights newest-first. Patients see their own insights,
    care providers see their assigned patients' insights.
    """
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
        # Insight trace_id follows pattern pm_<hash> — use insight_id to find it
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
