"""
Agent State — standard input/output contracts for all agents.

Every agent built on the foundation accepts ``AgentInput`` and returns
``AgentOutput``. This ensures consistent interfaces for routing, tracing,
and streaming regardless of the agent's internal implementation.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RequestPriority(str, Enum):
    """Priority levels for request routing and rate limiting."""

    CRITICAL = "critical"   # Care provider flagged urgent
    HIGH = "high"           # Care provider normal queries
    NORMAL = "normal"       # Patient queries
    LOW = "low"             # Background scans (proactive monitor)


class AgentContext(BaseModel):
    """Shared context passed to every agent run."""

    patient_id: str | None = None
    user_id: str | None = None
    user_role: str = Field(
        default="patient",
        description="'patient' or 'care_provider'.",
    )
    thread_id: str | None = None
    trace_id: str | None = None
    timezone: str | None = None
    priority: RequestPriority = RequestPriority.NORMAL
    patient_ids: list[str] = Field(
        default_factory=list,
        description="For care providers querying multiple patients.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentInput(BaseModel):
    """Standard input to any foundation agent."""

    message: str = Field(description="The user's message.")
    context: AgentContext = Field(default_factory=AgentContext)
    stream: bool = Field(
        default=False,
        description="Whether the client wants SSE streaming.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentOutput(BaseModel):
    """Standard output from any foundation agent."""

    model_config = {"protected_namespaces": ()}

    message: str = Field(description="The agent's response text.")
    is_ready: bool = Field(
        default=True,
        description="False if the agent needs clarification from the user.",
    )
    suggestions: list[dict[str, str]] = Field(
        default_factory=list,
        description="Suggested follow-up actions/questions.",
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured response data (intent, analysis, etc.).",
    )
    trace_id: str | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None
    model_id: str | None = None
