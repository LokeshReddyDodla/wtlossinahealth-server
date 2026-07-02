"""
Feedback endpoint — collects user thumbs up/down on agent responses.

Logs feedback scores to Langfuse for observability and evaluation.
"""

import logging
from typing import Optional

from fastapi import Depends
from pydantic import BaseModel, Field

from lib.core.container import container
from lib.ai_foundation.models.gateway import ModelGateway
from lib.dependencies.actor import Actor, get_current_actor
from lib.core.constants import ProfileTypeEnum
from rest_server.response_models import SuccessResponse

from .router import router
from .utils import enforce_rate_limit


class FeedbackRequest(BaseModel):
    """Request body for submitting feedback on an agent response."""

    trace_id: str = Field(..., min_length=1, max_length=100, description="The trace_id from the agent response.")
    thumbs_up: bool = Field(..., description="True for positive feedback, False for negative.")
    comment: Optional[str] = Field(None, max_length=1000, description="Optional free-text feedback.")


class FeedbackResponse(BaseModel):
    recorded: bool
    trace_id: str


@router.post("/feedback", response_model=SuccessResponse[FeedbackResponse])
async def submit_feedback(
    payload: FeedbackRequest,
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER, ProfileTypeEnum.ADMIN],
            check_permissions=False,
        )
    ),
):
    """Submit thumbs up/down feedback on an agent response.

    The feedback is logged to Langfuse as a score against the trace.
    """
    enforce_rate_limit(current_actor)
    score = 1.0 if payload.thumbs_up else 0.0

    # Log score to Langfuse
    recorded = False
    try:
        gateway: ModelGateway = container.resolve(ModelGateway)
        gateway.log_score(
            trace_id=payload.trace_id,
            name="user_feedback",
            value=score,
            comment=payload.comment,
        )
        recorded = True
    except Exception as exc:
        logging.getLogger(__name__).warning("Feedback scoring failed for trace %s: %s", payload.trace_id, exc)

    return SuccessResponse(
        message="Feedback recorded" if recorded else "Feedback noted",
        data=FeedbackResponse(recorded=recorded, trace_id=payload.trace_id),
    )
