"""
Feedback endpoint — collects user thumbs up/down on agent responses.

Feeds the fine-tuning pipeline by recording explicit quality signals
against captured training samples (matched by trace_id).
"""

from typing import Optional

from fastapi import Depends
from pydantic import BaseModel, Field

from lib.core.container import container
from lib.ai_foundation.eval.collector import FinetuneDataCollector
from lib.dependencies.actor import Actor, get_current_actor
from lib.core.constants import ProfileTypeEnum
from rest_server.response_models import SuccessResponse

from .router import router


class FeedbackRequest(BaseModel):
    """Request body for submitting feedback on an agent response."""

    trace_id: str = Field(..., description="The trace_id from the agent response.")
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
        )
    ),
):
    """Submit thumbs up/down feedback on an agent response.

    The feedback is recorded against the training sample identified by
    trace_id, which feeds the fine-tuning quality filter.
    """
    collector: FinetuneDataCollector = container.resolve(FinetuneDataCollector)

    score = 1.0 if payload.thumbs_up else 0.0
    recorded = await collector.add_feedback(
        sample_id=payload.trace_id,
        score=score,
        notes=payload.comment,
    )

    return SuccessResponse(
        message="Feedback recorded" if recorded else "Feedback noted (sample not found)",
        data=FeedbackResponse(recorded=recorded, trace_id=payload.trace_id),
    )
