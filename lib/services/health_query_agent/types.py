from enum import Enum
from typing import Any, Annotated, List, Optional, TypedDict

from lib.services.health_query_agent.state_constants import RESET


class HealthDataType(str, Enum):
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
    SMBG = "smbg"
    MEAL = "meal"
    FITNESS_OVERVIEW = "fitness_overview"
    FITNESS_DIST = "fitness_activity_distribution"
    FITNESS_INACTIVE = "fitness_inactive_periods"
    PROFILE = "profile"
    DOCUMENTS = "patient_document"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            return cls.__members__.get(value.upper())


def messages_reducer(old: list | None, new: Any):
    if new == RESET:
        return []

    if old is None:
        old = []

    if isinstance(new, list):
        return old + new

    raise ValueError(f"Invalid messages update: {new}")


class AgentState(TypedDict):
    from lib.services.health_query_agent.intent import QueryIntent

    messages: Annotated[list[dict], messages_reducer]
    intent: QueryIntent
    final_response: Optional[str]
    search_confidence: Optional[float]
    patient_ids: Optional[List[str]]
    user_role: Optional[str]
