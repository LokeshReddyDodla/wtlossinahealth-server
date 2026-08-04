"""Configuration for Fitness vector service sections."""

from dataclasses import dataclass
from typing import List, Literal, Optional


@dataclass
class FitnessSectionConfig:
    """Configuration for a Fitness section."""

    name: str
    keys: List[str]
    template_method: str
    call_signature: Literal["stats", "event"] = "stats"
    data_key: Optional[str] = None


FITNESS_OVERVIEW_CONFIG = FitnessSectionConfig(
    name="fitness_overview",
    keys=[
        "steps",
        "active_duration",
        "active_energy",
        "average_active_session_duration",
        "peak_hour",
        "peak_steps",
        "peak_active_energy",
        "days_with_data",
        "delta_steps",
        "delta_active_energy",
        "delta_active_duration",
    ],
    template_method="fitness_overview",
)

ACTIVITY_DISTRIBUTION_CONFIG = FitnessSectionConfig(
    name="fitness_activity_distribution",
    keys=[
        "morning_steps",
        "afternoon_steps",
        "evening_steps",
        "night_steps",
        "morning_duration",
        "afternoon_duration",
        "evening_duration",
        "night_duration",
        "morning_energy",
        "afternoon_energy",
        "evening_energy",
        "night_energy",
    ],
    template_method="fitness_activity_distribution",
)

# EVENTS → inactivity periods treated like events
INACTIVE_PERIOD_CONFIG = FitnessSectionConfig(
    name="fitness_inactive_periods",
    keys=["start_time", "end_time", "inactive_duration"],
    template_method="fitness_inactive_period",
    call_signature="event",
    data_key="fitness_inactive_periods",
)

FITNESS_SECTION_CONFIGS = {
    "fitness_overview": FITNESS_OVERVIEW_CONFIG,
    "fitness_activity_distribution": ACTIVITY_DISTRIBUTION_CONFIG,
    "fitness_inactive_periods": INACTIVE_PERIOD_CONFIG,
}

STATS_CONFIGS = {
    k: v
    for k, v in FITNESS_SECTION_CONFIGS.items()
    if v.call_signature == "stats"
}

EVENT_CONFIGS = {
    k: v
    for k, v in FITNESS_SECTION_CONFIGS.items()
    if v.call_signature == "event"
}


# Utility functions
def get_section_config(section_name: str) -> Optional[FitnessSectionConfig]:
    """Get configuration for a specific section by name."""
    return FITNESS_SECTION_CONFIGS.get(section_name)


def get_stats_section_names() -> List[str]:
    """Get all statistics section names."""
    return list(STATS_CONFIGS.keys())


def get_event_section_names() -> List[str]:
    """Get all event section names."""
    return list(EVENT_CONFIGS.keys())
