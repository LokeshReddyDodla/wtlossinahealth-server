"""
Product Bot — public SSE streaming endpoint for the marketing website chatbot.

No authentication required. Rate-limited by IP + session + global cap.
"""

from __future__ import annotations

import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from lib.ai_foundation.agents.product_bot import ProductBotAgent
from lib.ai_foundation.agents.state import AgentContext, AgentInput
from lib.ai_foundation.rate_limit.public_limiter import PublicRateLimiter
from lib.ai_foundation.streaming.sse import SSE_RESPONSE_HEADERS
from rest_server.response_models import SuccessResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/product-bot", tags=["Product Bot"])


# -- Request schema -----------------------------------------------------------


class ProductBotRequest(BaseModel):
    """Incoming chat message from a website visitor."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="The visitor's question.",
    )
    session_id: str = Field(
        ...,
        min_length=36,
        max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        description="Client-generated UUID v4 session identifier.",
    )


# -- Dependencies -------------------------------------------------------------


def _get_agent() -> ProductBotAgent:
    from lib.core.container import container

    return container.resolve(ProductBotAgent)


def _get_limiter() -> PublicRateLimiter:
    from lib.core.container import container

    return container.resolve(PublicRateLimiter)


# -- Helpers ------------------------------------------------------------------


def _resolve_ip(request: Request) -> str:
    """Extract client IP, respecting reverse proxy headers."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip", "")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(
    limiter: PublicRateLimiter, ip: str, session_id: str
) -> None:
    result = limiter.check_and_record(ip, session_id)
    if not result.allowed:
        retry_after = max(1, int(result.reset_at - time.time()))
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded ({result.layer}). Try again later.",
            headers={"Retry-After": str(retry_after)},
        )


# -- Endpoints ----------------------------------------------------------------


@router.post("/stream")
async def product_bot_stream(
    request: Request,
    payload: ProductBotRequest,
    agent: Annotated[ProductBotAgent, Depends(_get_agent)],
    limiter: Annotated[PublicRateLimiter, Depends(_get_limiter)],
):
    """Stream a product-knowledge answer via SSE. No auth required."""
    ip = _resolve_ip(request)
    _check_rate_limit(limiter, ip, payload.session_id)

    agent_input = AgentInput(
        message=payload.message,
        context=AgentContext(
            thread_id=payload.session_id,
            metadata={"ip": ip},
        ),
        stream=True,
    )

    return StreamingResponse(
        agent.run_stream(agent_input),
        media_type="text/event-stream",
        headers=SSE_RESPONSE_HEADERS,
    )


@router.post("/query")
async def product_bot_query(
    request: Request,
    payload: ProductBotRequest,
    agent: Annotated[ProductBotAgent, Depends(_get_agent)],
    limiter: Annotated[PublicRateLimiter, Depends(_get_limiter)],
):
    """Non-streaming product-bot response. No auth required."""
    ip = _resolve_ip(request)
    _check_rate_limit(limiter, ip, payload.session_id)

    agent_input = AgentInput(
        message=payload.message,
        context=AgentContext(
            thread_id=payload.session_id,
            metadata={"ip": ip},
        ),
        stream=False,
    )

    output = await agent.run(agent_input)
    return SuccessResponse(
        message="OK",
        data=output.model_dump(exclude_none=True),
    )
