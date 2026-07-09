"""
Shared Memory Protocol — defines the interface for cross-agent patient
knowledge and conversation state.

All agents share a single MemoryStore so that facts learned by one agent
(e.g. "patient is vegetarian" from the meal agent) are available to all
others (e.g. the health query agent when recommending foods).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Memory Models
# ---------------------------------------------------------------------------


class MemoryCategory(str, Enum):
    """Categories for patient memories."""

    CONDITION = "condition"      # diabetes type, allergies, medical conditions
    GOAL = "goal"               # health goals, weight targets
    PREFERENCE = "preference"   # diet, cuisine, activity preferences
    HEALTH = "health"           # measurements: weight, height, BMI
    LIFESTYLE = "lifestyle"     # activity level, sleep, smoking, alcohol
    OTHER = "other"             # uncategorized


class MemorySource(str, Enum):
    """How a memory was created."""

    USER_EXPLICIT = "user_explicit"     # "remember that I'm vegetarian"
    AUTO_EXTRACTED = "auto_extracted"   # extracted from conversation
    SYSTEM = "system"                   # from profile sync


class MemoryFact(BaseModel):
    """A single memory about a patient, stored long-term across agents.

    Memories are keyed by ``key`` (e.g. "health_goal", "dietary_preference").
    Keys are normalized: lowercase, stripped, underscores for spaces.
    """

    key: str = Field(description="Normalized memory key, e.g. 'health_goal', 'dietary_preference'.")
    value: Any = Field(description="Memory value (any JSON-serializable type).")
    category: str = Field(
        default=MemoryCategory.OTHER.value,
        description="Memory category: condition, goal, preference, health, lifestyle, other.",
    )
    source: str = Field(
        default=MemorySource.AUTO_EXTRACTED.value,
        description="How this memory was created: user_explicit, auto_extracted, system.",
    )
    agent_id: str | None = Field(
        default=None,
        description="Which agent produced this memory.",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence in this memory. 1.0 = confirmed by user.",
    )
    is_permanent: bool = Field(
        default=False,
        description="Permanent memories (allergies, diabetes type) are never auto-expired.",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    created_at: datetime | None = Field(
        default=None,
        description="When this memory was FIRST learned. Set on insert, preserved across updates.",
    )


# Higher number = more authoritative. An auto-extraction must never
# overwrite what the user explicitly told us.
SOURCE_PRIORITY: dict[str, int] = {
    MemorySource.USER_EXPLICIT.value: 2,
    MemorySource.SYSTEM.value: 1,
    MemorySource.AUTO_EXTRACTED.value: 0,
}


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
    patient_ids: list[str] = Field(
        default_factory=list,
        description="Patient IDs this thread is about. Resolved to names/pics at query time.",
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
    last_assistant_question: str | None = Field(
        default=None,
        description=(
            "Open question the agent asked in its most recent reply, if any. "
            "Cleared when the next reply asks nothing. Lets the agent avoid "
            "re-asking ignored questions and resolve short answers after the "
            "raw turn scrolls out of the history window."
        ),
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

    # -- Patient Memories (cross-agent, long-term) ---

    async def get_patient_facts(self, patient_id: str) -> list[MemoryFact]:
        """Retrieve all known memories about a patient."""
        ...

    async def upsert_patient_facts(
        self, patient_id: str, facts: list[MemoryFact]
    ) -> None:
        """Merge memories into the patient's store.

        Existing memories with the same key are updated if the new memory
        has higher confidence or is more recent.
        """
        ...

    async def delete_patient_fact(self, patient_id: str, key: str) -> bool:
        """Delete a specific memory by key. Returns True if deleted."""
        ...

    async def delete_patient_facts(self, patient_id: str, keys: list[str]) -> int:
        """Delete multiple memories by keys. Returns number of deleted records."""
        ...

    # -- Conversation Turns ---

    async def count_thread_turns(self, thread_id: str) -> int:
        """Count total turns in a thread without loading them."""
        ...

    async def get_first_thread_turns(self, thread_id: str, *, limit: int = 2) -> list[ConversationTurn]:
        """Retrieve the earliest turns from a thread (for title generation)."""
        ...

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

    async def append_turns_batch(
        self, thread_id: str, turns: list[ConversationTurn]
    ) -> None:
        """Append multiple turns to a conversation thread in one write when supported."""
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
