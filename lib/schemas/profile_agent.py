"""Schemas for the unified Profile Agent.

Replaces `patient_onboarding_agent` and `profile_update_agent`. This agent
discovers missing fields by introspecting `CompletePatientProfile` and
auto-detects its mode (onboarding vs update) from the patient's current
state.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class DraftState(str, Enum):
    """Active-state lifecycle for a profile-agent draft.

    Terminal states (COMPLETED, CANCELLED) are kept in Mongo for history;
    the next user message after a terminal state creates a fresh draft.
    """

    COLLECTING = "collecting"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class AgentMode(str, Enum):
    """Conversational mode auto-detected each turn from patient state.

    Computed from the fraction of required (and gate-satisfied) fields
    present on the patient — `profile_completion.is_complete` is NOT used
    as the source of truth because agents themselves write it.
    """

    ONBOARDING_FRESH = "onboarding_fresh"
    ONBOARDING_RESUMING = "onboarding_resuming"
    HYBRID = "hybrid"
    UPDATE = "update"


ActionType = Literal[
    "set",
    "remove",
    "show_draft",
    "confirm_all",
    "cancel_all",
    "query",
]


class LLMAction(BaseModel):
    """A single intent-action extracted by the LLM from the user turn."""

    action: ActionType
    field: Optional[str] = None
    value: Optional[str] = None


class LLMResponse(BaseModel):
    """Structured output the LLM is asked to emit per turn."""

    actions: List[LLMAction] = Field(default_factory=list)
    reply: str = ""


class ProfileAgentChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class ProfileAgentStartRequest(BaseModel):
    restart: bool = False


class ProfileAgentChatResponse(BaseModel):
    reply: str
    state: str = Field(description="Draft state: collecting/reviewing/completed/cancelled")
    mode: str = Field(description="Agent mode this turn: onboarding_fresh/onboarding_resuming/hybrid/update")
    draft_changes: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Pending draft changes keyed by field.",
    )
    applied_changes: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Fields actually written to DB. Set only when state=completed.",
    )
    next_field: Optional[str] = Field(
        default=None,
        description="Field the agent is proactively asking about (onboarding-like modes).",
    )


class SessionSummaryResponse(BaseModel):
    state: str
    mode: str
    draft_changes: Dict[str, Any] = Field(default_factory=dict)
    message_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class GapFieldInfo(BaseModel):
    field: str
    label: str
    section: str
    entity: str
    type: str
    required: bool


class GapReport(BaseModel):
    mode: str
    completion_pct: float
    sections: Dict[str, bool] = Field(
        description="Per-section completion: section_key → is_complete (gate-aware)."
    )
    missing_fields: List[GapFieldInfo] = Field(
        description="Fields that are required, gate-satisfied, and currently missing — in deterministic order."
    )


class DraftDocument(BaseModel):
    """Shape of documents in the `profile_agent_conversations` collection.

    One *active* document per patient enforced by a unique partial index.
    """

    patient_id: str
    status: str = "active"  # "active" | "completed" | "cancelled"
    state: str = DraftState.COLLECTING.value
    draft_changes: Dict[str, Any] = Field(default_factory=dict)
    messages: List[Dict[str, str]] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
