"""
Proactive Insights — history and feedback endpoints.

GET  /health-query-agent/proactive-insights?patient_id=...&limit=20
POST /health-query-agent/proactive-insights/feedback
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

from lib.ai_foundation.agents.proactive_monitor.insight_tracker import InsightTracker
from lib.ai_foundation.models.gateway import ModelGateway
from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_insight_tracker,
    get_model_gateway,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from rest_server.response_models import SuccessResponse

from .router import router
from .utils import enforce_rate_limit, parse_patient_uuid


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
    from_date: Optional[datetime] = Query(
        None, description="ISO 8601 datetime — include insights created at or after this time"
    ),
    to_date: Optional[datetime] = Query(
        None, description="ISO 8601 datetime — include insights created at or before this time"
    ),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER, ProfileTypeEnum.ADMIN],
            check_permissions=False,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
    tracker: InsightTracker = Depends(get_insight_tracker),
):
    """Get recent proactive insight history for a patient.

    Returns insights newest-first. Patients see their own insights,
    care providers see their assigned patients' insights.
    """
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=parse_patient_uuid(patient_id),
        care_provider_access_service=care_provider_access_service,
    )

    docs = await tracker.get_history(
        str(verified_pid),
        limit=limit,
        from_date=from_date,
        to_date=to_date,
    )

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
    tracker: InsightTracker = Depends(get_insight_tracker),
    gateway: ModelGateway = Depends(get_model_gateway),
):
    """Submit feedback on a proactive insight.

    Logs to Langfuse as a score for quality tracking.
    """
    enforce_rate_limit(current_actor)

    recorded = False
    try:
        doc = await tracker.get_by_insight_id(payload.insight_id)
        if not doc or not doc.get("patient_id"):
            raise HTTPException(status_code=404, detail="Insight not found")
        await resolve_patient_access(
            actor=current_actor,
            patient_id=parse_patient_uuid(str(doc["patient_id"])),
            care_provider_access_service=care_provider_access_service,
        )
        trace_id = doc.get("trace_id") if doc else None
        if not trace_id:
            raise ValueError("No trace_id found for insight feedback")
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
