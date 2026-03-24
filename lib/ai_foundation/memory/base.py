"""
Shared Memory Protocol — defines the interface for cross-agent patient
knowledge and conversation state.

All agents share a single MemoryStore so that facts learned by one agent
(e.g. "patient is vegetarian" from the meal agent) are available to all
others (e.g. the health query agent when recommending foods).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class MemoryFact(BaseModel):
    """A single fact about a patient, stored long-term across agents.

    Facts are keyed by ``key`` (e.g. "goal", "weight", "dietary_preference").
    Multiple agents can contribute facts; ``agent_id`` tracks the source.
    """

    key: str = Field(description="Fact key, e.g. 'goal', 'weight', 'fasting_context'.")
    value: Any = Field(description="Fact value (any JSON-serializable type).")
    source: str = Field(
        default="user",
        description="Where this fact came from: 'user', 'agent', 'system'.",
    )
    agent_id: str | None = Field(
        default=None,
        description="Which agent produced this fact.",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence in this fact. 1.0 = confirmed by user.",
    )
    confirmed: bool = Field(
        default=True,
        description="Whether the user has explicitly confirmed this fact.",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class ConversationTurn(BaseModel):
    """A single turn in a conversation thread."""

    role: str = Field(description="Message role: 'user', 'assistant', 'system'.")
    content: str = Field(description="Message content.")
    agent_id: str = Field(
        default="",
        description="Which agent produced this turn (empty for user turns).",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional data: intent, response metadata, etc.",
    )


class ThreadSummary(BaseModel):
    """Compacted summary of a conversation thread."""

    thread_id: str
    title: str = Field(
        default="",
        description="Short human-readable title for the thread (auto-generated from first message).",
    )
    summary: str = Field(description="Natural language summary of the conversation.")
    domains: list[str] = Field(
        default_factory=list,
        description="Active health domains in this thread.",
    )
    goal: str | None = Field(
        default=None,
        description="Active patient goal in this thread.",
    )
    date_scope: str | None = Field(
        default=None,
        description="Active date scope (e.g. 'this_week').",
    )
    turn_count: int = 0
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class MemoryStore(Protocol):
    """Protocol that all memory backends implement.

    Any class satisfying this protocol can be injected into agents
    as their memory store.
    """

    # -- Patient Facts (cross-agent, long-term) ---

    async def get_patient_facts(self, patient_id: str) -> list[MemoryFact]:
        """Retrieve all known facts about a patient."""
        ...

    async def upsert_patient_facts(
        self, patient_id: str, facts: list[MemoryFact]
    ) -> None:
        """Merge facts into the patient's fact store.

        Existing facts with the same key are updated if the new fact
        has higher confidence or is more recent.
        """
        ...

    # -- Conversation Turns ---

    async def get_thread_turns(
        self, thread_id: str, *, limit: int = 20
    ) -> list[ConversationTurn]:
        """Retrieve recent turns from a conversation thread."""
        ...

    async def append_turn(
        self, thread_id: str, turn: ConversationTurn
    ) -> None:
        """Append a turn to a conversation thread."""
        ...

    # -- Thread Summaries ---

    async def get_thread_summary(self, thread_id: str) -> ThreadSummary | None:
        """Retrieve the latest compacted summary for a thread."""
        ...

    async def save_thread_summary(
        self, thread_id: str, summary: ThreadSummary
    ) -> None:
        """Save or update a thread summary."""
        ...
