"""
Health Query Contracts — schemas for intent extraction, response, and
domain classification.

Backward-compatible with the existing QueryResponse API contract so that
clients don't need changes when switching to the foundation agent.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class HealthDataType(str, Enum):
    """Canonical health data types available in the vector store."""

    CGM_RANGE = "cgm_range_stats"
    CGM_SUMMARY = "cgm_summary_stats"
    HYPER_STATS = "hyper_stats"
    HYPO_STATS = "hypo_stats"
    RAPID_SPIKE = "rapid_spike_stats"
    RAPID_DROP = "rapid_drop_stats"
    HYPER_EVENT = "hyper_event"
    HYPO_EVENT = "hypo_event"
    RAPID_SPIKE_EVENT = "rapid_spike_event"
    RAPID_DROP_EVENT = "rapid_drop_event"
    TIME_PERIOD = "time_period_stats"
    AGP = "agp_point"
    CGM_SEMANTIC_WINDOW = "cgm_semantic_window"
    SMBG = "smbg"
    MEAL = "meal"
    FITNESS_OVERVIEW = "fitness_overview"
    FITNESS_DIST = "fitness_activity_distribution"
    FITNESS_INACTIVE = "fitness_inactive_periods"
    VITAL = "vital"
    SLEEP = "sleep"
    SLEEP_CHECKIN = "sleep_checkin"
    MOOD_ENTRY = "mood_entry"
    SYMPTOM_ENTRY = "symptom_entry"
    DIET_PLAN = "diet_plan"
    FITNESS_PLAN = "fitness_plan"
    PROFILE = "profile"
    DOCUMENTS = "patient_document"
    MEDICATION = "medication"
    PATIENT_WORKOUT = "patient_workout"
    BODY_COMPOSITION = "body_composition"

    @classmethod
    def _missing_(cls, value: object):
        if isinstance(value, str):
            return cls.__members__.get(value.upper())
        return None


class DomainName(str, Enum):
    """High-level health domains."""

    MEAL = "meal"
    CGM = "cgm"
    SMBG = "smbg"
    FITNESS = "fitness"
    PROFILE = "profile"
    DOCUMENTS = "documents"
    SLEEP = "sleep"
    VITALS = "vitals"
    MOOD = "mood"
    SYMPTOMS = "symptoms"
    PLANS = "plans"
    MEDICATION = "medication"
    WORKOUT = "workout"
    BODY_COMPOSITION = "body_composition"


# Human-readable domain list for prompts — derived from DomainName enum.
AVAILABLE_HEALTH_DOMAINS = ", ".join(d.value for d in DomainName)


# Maps each HealthDataType to its parent domain for specialist routing
DOMAIN_MAPPING: dict[DomainName, list[HealthDataType]] = {
    DomainName.CGM: [
        HealthDataType.CGM_RANGE, HealthDataType.CGM_SUMMARY,
        HealthDataType.HYPER_STATS, HealthDataType.HYPO_STATS,
        HealthDataType.RAPID_SPIKE, HealthDataType.RAPID_DROP,
        HealthDataType.HYPER_EVENT, HealthDataType.HYPO_EVENT,
        HealthDataType.RAPID_SPIKE_EVENT, HealthDataType.RAPID_DROP_EVENT,
        HealthDataType.TIME_PERIOD, HealthDataType.AGP,
        HealthDataType.CGM_SEMANTIC_WINDOW,
    ],
    DomainName.MEAL: [HealthDataType.MEAL],
    DomainName.FITNESS: [
        HealthDataType.FITNESS_OVERVIEW,
        HealthDataType.FITNESS_DIST,
        HealthDataType.FITNESS_INACTIVE,
    ],
    DomainName.SMBG: [HealthDataType.SMBG],
    DomainName.VITALS: [HealthDataType.VITAL],
    DomainName.SLEEP: [HealthDataType.SLEEP, HealthDataType.SLEEP_CHECKIN],
    DomainName.MOOD: [HealthDataType.MOOD_ENTRY],
    DomainName.SYMPTOMS: [HealthDataType.SYMPTOM_ENTRY],
    DomainName.PLANS: [HealthDataType.DIET_PLAN, HealthDataType.FITNESS_PLAN],
    DomainName.PROFILE: [HealthDataType.PROFILE],
    DomainName.DOCUMENTS: [HealthDataType.DOCUMENTS],
    DomainName.MEDICATION: [HealthDataType.MEDICATION],
    DomainName.WORKOUT: [HealthDataType.PATIENT_WORKOUT],
    DomainName.BODY_COMPOSITION: [HealthDataType.BODY_COMPOSITION],
}

# Reverse mapping: HealthDataType → DomainName
_TYPE_TO_DOMAIN: dict[HealthDataType, DomainName] = {}
for _domain, _types in DOMAIN_MAPPING.items():
    for _dt in _types:
        _TYPE_TO_DOMAIN[_dt] = _domain

# Roles that see provider-formatted evidence (clinical framing, patient
# named in third person). Everything else gets the patient framing. Any
# role check MUST use this set — scattered ad-hoc tuples diverge.
PROVIDER_VIEW_ROLES = frozenset({"care_provider", "research", "admin"})

# Map DomainName enum to specialist domain key
_DOMAIN_TO_SPECIALIST: dict[DomainName, str] = {
    DomainName.CGM: "glucose",
    DomainName.SMBG: "glucose",
    DomainName.MEAL: "nutrition",
    DomainName.FITNESS: "fitness",
    DomainName.VITALS: "vitals",
    DomainName.SLEEP: "sleep",
    DomainName.MOOD: "sleep",  # mood routed to sleep/wellness specialist
    DomainName.SYMPTOMS: "sleep",  # symptoms routed to sleep/wellness specialist
    DomainName.PLANS: "nutrition",  # plans routed to nutrition specialist
    DomainName.DOCUMENTS: "documents",
    DomainName.WORKOUT: "fitness",
    DomainName.BODY_COMPOSITION: "vitals",
}


def resolve_domains(data_types: list[HealthDataType]) -> list[DomainName]:
    """Map data types from intent extraction to unique domains."""
    domains: set[DomainName] = set()
    for dt in data_types:
        domain = _TYPE_TO_DOMAIN.get(dt)
        if domain:
            domains.add(domain)
    return sorted(domains, key=lambda d: d.value)


def resolve_specialist_domains(data_types: list[HealthDataType]) -> list[str]:
    """Map data types to specialist domain keys (glucose, nutrition, fitness)."""
    specialists: set[str] = set()
    for dt in data_types:
        domain = _TYPE_TO_DOMAIN.get(dt)
        if domain:
            specialist = _DOMAIN_TO_SPECIALIST.get(domain)
            if specialist:
                specialists.add(specialist)
    return sorted(specialists)


def expand_to_domain_types(data_types: list[HealthDataType]) -> list[HealthDataType]:
    """Expand each requested type to its whole domain family (via DOMAIN_MAPPING).

    A glucose question naming one type ("any spikes?") otherwise retrieves only
    the intent extractor's narrow pick — e.g. daily summaries without the
    rapid_spike/hypo EVENT records — and the agent then truthfully-but-wrongly
    reports "no spikes" because the events were never fetched. Expanding to the
    domain family makes the single-agent path fetch the same complete picture
    the specialist path already does. Order-preserving and deduplicated.
    """
    seen: set[HealthDataType] = set()
    out: list[HealthDataType] = []
    for dt in data_types:
        domain = _TYPE_TO_DOMAIN.get(dt)
        family = DOMAIN_MAPPING[domain] if domain else [dt]
        for t in family:
            if t not in seen:
                seen.add(t)
                out.append(t)
    return out


class ResponseMode(str, Enum):
    """How the agent should format its response."""

    LIST = "list"
    SUMMARIZE = "summarize"
    EVALUATE = "evaluate"
    COMPARE = "compare"
    RECOMMEND = "recommend"
    CLARIFY = "clarify"


# ---------------------------------------------------------------------------
# Intent extraction (LLM-produced)
# ---------------------------------------------------------------------------


class DateRange(BaseModel):
    start: datetime = Field(description="Inclusive start of date range.")
    end: datetime = Field(description="Exclusive end of date range.")


class TimeRange(BaseModel):
    start_hour: int | None = Field(None, description="Start hour (0-23), inclusive.")
    end_hour: int | None = Field(None, description="End hour (0-23), exclusive.")


class NumericRange(BaseModel):
    gte: float | None = None
    lte: float | None = None
    gt: float | None = None
    lt: float | None = None


class NumericFilter(BaseModel):
    key: str = Field(description="Exact Qdrant payload key.")
    range_condition: NumericRange


class SuggestedAction(BaseModel):
    # Optional app action for chip rendering (e.g. "log_meal" opens the meal
    # sheet). None = plain follow-up query chip (tap sends `description`).
    action: str | None = None
    label: str = Field(..., description="Short button text.")
    description: str = Field(..., description="Complete follow-up question.")


class QueryIntent(BaseModel):
    """Structured intent extracted from the user's message by the LLM.

    This is the response_model passed to ModelGateway.extract().
    """

    is_ready: bool = Field(
        ..., description="True if enough info to execute a data query.",
    )
    data_types: list[HealthDataType] = Field(
        default_factory=list,
        description="Canonical data types needed.",
    )
    date_range: DateRange | None = Field(
        None, description="Main date range for the query.",
    )
    hour_range: TimeRange | None = Field(
        None, description="Hour-of-day filter.",
    )
    month_filters: list[int] | None = Field(
        None, description="Month numbers (1-12) if mentioned.",
    )
    time_buckets: list[str] = Field(
        default_factory=list,
        description="Time-of-day buckets: morning, afternoon, evening, night.",
    )
    numeric_filters: list[NumericFilter] = Field(
        default_factory=list,
        description="Numeric constraints (e.g., glucose > 200).",
    )
    clarification_msg: str | None = Field(
        None, description="Friendly message when is_ready is False.",
    )
    suggestions: list[SuggestedAction] = Field(
        default_factory=list,
        description="Suggested follow-up actions.",
    )
    confidence: float | None = Field(
        None, description="Confidence score 0.0-1.0.",
    )
    # Memory management — detected from user messages like "remember X", "forget X"
    memory_action: Literal["add", "delete", "list"] | None = Field(
        None, description="Memory action: 'add', 'delete', 'list', or null if not a memory command.",
    )
    memory_key: str | None = Field(
        None, description="For add/delete: the memory key (e.g. 'dietary_preference').",
    )
    memory_value: str | None = Field(
        None, description="For add: the memory value (e.g. 'vegetarian').",
    )
    # Entity types must stay in sync with bubbles.AWAIT_ENTITY_TYPES — the
    # reply-side [[AWAIT]] marker and this query-side signal register the same
    # pending request, and only entities with a proactive-event producer can
    # be honored.
    awaits_log: Literal["meal", "smbg", "symptom"] | None = Field(
        None,
        description=(
            "Set when the user names a health entry they intend to log for "
            "analysis but haven't yet ('just ate lunch but haven't logged it "
            "— can you check it?'). That entity's eventual log continues this "
            "conversation. Null for normal queries and past-tense lookups."
        ),
    )



class QueryResponse(BaseModel):
    """Response returned to the client. Matches the existing API contract."""

    type: str = "response"
    is_ready: bool
    user_message: str
    message: str
    turn_number: int = 0
    data_types: list[str] | None = None
    date_range: dict | None = None
    hour_range: dict | None = None
    month_filters: list[int] | None = None
    time_buckets: list[str] | None = None
    numeric_filters: list[dict] | None = None
    final_response: str | None = None
    clarification_msg: str | None = None
    suggestions: list[dict] | None = None
    confidence: float | None = None
    search_confidence: float | None = None
    coverage_confidence: float | None = None
    reflection_confidence: float | None = None
    data_gaps: list[str] | None = None
    data_conflicts: list[str] | None = None
    trace_id: str | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None


class ProactiveNarration(BaseModel):
    """The brain's decision + copy for a proactive push.

    ``notify`` is the brain's own judgment that the event is worth an unprompted
    interruption; when False the other fields are ignored and nothing is sent.
    The brain writes only the words — category and severity are decided
    deterministically by the caller from the trigger, never invented here.
    """

    notify: bool = Field(description="Whether this event warrants a proactive push at all.")
    title: str = Field(default="", max_length=50, description="Push title. English; translated on delivery.")
    body: str = Field(default="", max_length=180, description="Push body, grounded in investigated data. English.")
    suggested_query: str | None = Field(
        default=None, description="One follow-up the patient could tap to open the chat."
    )


class PatientBrief(BaseModel):
    """Provider-facing clinical synthesis — an at-a-glance read of the patient's
    overall recent state, not a data surface. Every field is grounded in the
    investigated data; the structuring step never adds a claim or number the
    analysis didn't state. When the record is too sparse to judge, assessment is
    'insufficient_data'."""

    assessment: Literal["responding", "watch", "at_risk", "insufficient_data"] = Field(
        description=(
            "Overall read, matching the verdict's lead — responding when it leads "
            "positive (even with a watch-item in the tail), watch when genuinely "
            "mixed, at_risk when deteriorating/high-risk, insufficient_data when a "
            "response can't be judged at all. Drives the status spine."
        ),
    )
    verdict: str = Field(
        max_length=120,
        description="One-line headline leading with the read, e.g. 'Responding well — holding steady across recent weeks'.",
    )
    narrative: str = Field(
        description=(
            "1-2 sentences: what's driving the read and the single thing to watch, "
            "naming the key figures in context within the prose (never as standalone "
            "tiles); honest about data gaps. Bold (**…**) only the single most "
            "important phrase — not every figure. English."
        ),
    )


class PatientCardChip(BaseModel):
    label: str = Field(max_length=40, description="One concrete metric or flag, e.g. 'Time in range 82%' or 'Watch: late snacks'.")
    tone: Literal["good", "watch", "info"] = Field(
        default="info",
        description="good = reassuring/on-track, watch = gentle caution, info = neutral fact.",
    )


class PatientCardSource(BaseModel):
    label: str = Field(max_length=48, description="What the guidance rests on, e.g. 'CGM · last 7 days'.")


class PatientAnswerCard(BaseModel):
    """A provider's health-agent answer reshaped for the patient — short, plain
    language. A pure formatting step: never introduces a number, claim, or
    recommendation the source answer did not state.

    ``kind`` discriminates the chat's custom-card renderer; every rich card
    shares the metadata.type='custom' envelope and is told apart by it."""

    kind: Literal["ai_answer"] = Field(default="ai_answer", description="Card discriminator for the chat renderer.")
    title: str = Field(max_length=60, description="Short, plain headline of the takeaway, e.g. 'Your morning readings look stable'.")
    takeaway: str = Field(max_length=140, description="One reassuring, honest sentence — the single thing the patient should know. Also used as the notification text.")
    points: list[str] = Field(
        default_factory=list,
        description="2-4 short plain-language points supporting the takeaway. No jargon; each ≤120 chars.",
    )
    chips: list[PatientCardChip] = Field(
        default_factory=list,
        description="Optional metric/flag chips — only for figures the source answer actually stated.",
    )
    sources: list[PatientCardSource] = Field(
        default_factory=list,
        description="Optional data the answer drew on, for a 'why & sources' expander.",
    )
