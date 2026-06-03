"""
Research Agent — Pydantic contracts.

The shapes that flow between the planner, executor, tools, and responder.
These are intentionally distinct from ``AgentInput``/``AgentOutput`` in
``lib/ai_foundation/agents/state.py`` — research has its own input shape
(cohort + question, not patient + question) and its own output shape
(spec + execution + answer).

The agent still exposes ``run()``/``run_stream()`` so callers can adapt
to the standard ``AgentInput``/``AgentOutput`` interface; the standard
contracts are accepted as a thin convenience and internally translated
to ``ResearchInput``.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Cohort selection ─────────────────────────────────────────────────────────


class CohortRefKind(str, Enum):
    """How the caller is identifying the cohort."""

    IDS = "ids"           # Explicit patient_id list (Phase 1 default).
    SAVED = "saved"       # Reference to ai_cohorts.cohort_id (Phase 2).
    PANEL = "panel"       # "My whole assigned panel" (Phase 1 returns
                          # NotImplementedError — needs new access-service
                          # method; pass explicit IDs for now).


class CohortRef(BaseModel):
    """Reference to the cohort being researched."""

    kind: CohortRefKind = Field(description="How to resolve the cohort.")
    ids: list[str] | None = Field(
        default=None,
        description="Explicit patient IDs (used when kind == ids).",
    )
    cohort_id: str | None = Field(
        default=None,
        description="Saved cohort identifier (used when kind == saved).",
    )


# ── Cohort spec (the planner's structured output) ────────────────────────────


class CohortIntent(str, Enum):
    """What kind of question this is — drives the executor's path choice."""

    AGGREGATE = "aggregate"
    """Count / distribution. One call to ``cohort_aggregate``."""

    MATCH = "match"
    """One criterion → list of matching patient IDs. ``cohort_match``."""

    MATCH_AND_COUNT = "match_and_count"
    """Multi-criterion intersection with funnel. ``cohort_intersect``."""

    RANK = "rank"
    """Top-K patients by a precomputed criterion. ``rank_cohort``.
    Phase 1 falls back to a heuristic since scorecards don't exist yet."""

    FIND = "find"
    """Identify a cohort by condition. ``find_cohort``."""

    RESEARCH = "research"
    """Per-patient deep extraction. Mode 3 — deferred to Phase 3."""


class CohortCombinator(str, Enum):
    AND = "AND"
    OR = "OR"
    NOT = "NOT"


class CohortOutput(str, Enum):
    """What the executor should return."""

    COUNT = "count"
    IDS = "ids"
    IDS_WITH_FUNNEL = "ids_with_funnel"
    TOP_K = "top_k"
    EXTRACTION = "extraction"   # Mode 3


class Criterion(BaseModel):
    """One filter against a Qdrant data type or scorecard field."""

    data_type: str = Field(
        description=(
            "Qdrant data_type (e.g. 'hypo_event', 'sleep', 'meal'), OR "
            "a scorecard field (Phase 2+). The executor decides the backend."
        ),
    )
    filter: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Filter expression. For Qdrant: keyword/range conditions like "
            "{'hours': {'lt': 6}} or {'protein_g': {'lt': 20}}. For scorecards: "
            "field comparisons. Empty dict means 'any record of this data_type'."
        ),
    )
    window: str = Field(
        default="7d",
        description="Time window: '7d', '14d', '30d', '90d', or 'all'.",
    )
    label: str | None = Field(
        default=None,
        description="Human-readable label for funnel narration (auto-generated if omitted).",
    )


class CohortSpec(BaseModel):
    """The planner's structured interpretation of the user's question."""

    intent: CohortIntent
    criteria: list[Criterion] = Field(default_factory=list)
    combinator: CohortCombinator = CohortCombinator.AND
    output: CohortOutput
    k: int | None = Field(
        default=None,
        description="For RANK / TOP_K outputs.",
    )
    metric: str | None = Field(
        default=None,
        description=(
            "For AGGREGATE intent: 'count_unique_patients', 'count_records', "
            "or 'facet:<field>'."
        ),
    )
    condition: str | None = Field(
        default=None,
        description="For FIND intent: the condition / disease name to search for.",
    )
    followup_hint: str | None = Field(
        default=None,
        description=(
            "Free-text hint from the user's wording — e.g. 'show_top_3', "
            "'with_breakdown'. The responder may act on it."
        ),
    )


# ── Execution output (from executor → reasoning → responder) ─────────────────


class FunnelStep(BaseModel):
    """One row in the multi-criterion intersection funnel."""

    step: str = Field(description="Human-readable label (e.g. 'cohort', 'hypo_event last 7d').")
    count: int = Field(description="How many patients remain after this step.")


class ExecutionResultKind(str, Enum):
    INLINE = "inline"
    """Result computed synchronously — values are populated."""

    JOB_CREATED = "job_created"
    """Async job dispatched (Mode 3) — caller must poll ``job_id``."""

    NOT_IMPLEMENTED = "not_implemented"
    """Path not available in this phase — see ``reason``."""


class ExecutionResult(BaseModel):
    """What the executor returns to the reasoning engine."""

    kind: ExecutionResultKind = ExecutionResultKind.INLINE
    funnel: list[FunnelStep] = Field(default_factory=list)
    final_ids: list[str] = Field(default_factory=list)
    final_count: int = 0
    sample_rows: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Up to 3-5 representative rows for the responder to narrate.",
    )
    aggregate_value: dict[str, Any] | None = Field(
        default=None,
        description="For AGGREGATE intent: {'patient_count': 47, 'total_records': 312}.",
    )
    path: Literal["scorecard", "qdrant_fallback", "mongo", "hybrid"] | None = Field(
        default=None,
        description="Which backend produced the result. Useful for telemetry + trust tags.",
    )
    # Mode 3 fields
    job_id: str | None = None
    eta: str | None = None
    # Diagnostics
    reason: str | None = Field(
        default=None,
        description="If kind == NOT_IMPLEMENTED, explains why.",
    )
    cost_usd: float = 0.0
    latency_ms: int = 0


# ── Agent I/O ────────────────────────────────────────────────────────────────


class HistoryTurn(BaseModel):
    """One prior conversation turn — used to give the planner + responder context.

    The caller (REST endpoint / frontend) is responsible for trimming this to
    a recent window. The planner sees ``user`` and ``assistant`` roles.
    """

    role: Literal["user", "assistant"] = Field(description="'user' or 'assistant'.")
    content: str = Field(description="The text of the turn.")


class ResearchInput(BaseModel):
    """Input to the research agent."""

    question: str = Field(description="The provider's research question.")
    cohort: CohortRef = Field(description="Cohort to research over.")
    provider_id: str | None = Field(
        default=None,
        description="Identifies the calling provider — used for audit logs and access scoping.",
    )
    history: list[HistoryTurn] = Field(
        default_factory=list,
        description=(
            "Prior conversation turns (most recent last). Lets the planner "
            "resolve references like 'those 17' and the responder maintain "
            "continuity. Caller should cap to a reasonable window (e.g. last 6 turns)."
        ),
    )
    trace_id: str | None = None
    stream: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchOutput(BaseModel):
    """Output from the research agent."""

    model_config = {"protected_namespaces": ()}

    answer: str = Field(description="The natural-language response for the provider.")
    spec: CohortSpec = Field(description="The planner's interpretation of the question.")
    execution: ExecutionResult = Field(description="What the executor actually did.")
    suggestions: list[dict[str, str]] = Field(default_factory=list)
    cost_usd: float | None = None
    latency_ms: int | None = None
    model_id: str | None = None
    trace_id: str | None = None
    audit_id: str | None = None


__all__ = [
    "CohortRefKind",
    "CohortRef",
    "CohortIntent",
    "CohortCombinator",
    "CohortOutput",
    "Criterion",
    "CohortSpec",
    "FunnelStep",
    "ExecutionResultKind",
    "ExecutionResult",
    "HistoryTurn",
    "ResearchInput",
    "ResearchOutput",
]
