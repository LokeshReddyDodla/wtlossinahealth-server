from dataclasses import dataclass
from typing import Dict, List, Literal, Optional
from enum import Enum


class ReportPeriodType(str, Enum):
    OVERALL = "overall"
    DAY_WISE = "day_wise"
    WEEK_WISE = "week_wise"


@dataclass
class CGMSectionConfig:
    name: str
    keys: List[str]
    template_method: str
    call_signature: Literal["event", "stats"] = "stats"
    data_key: Optional[str] = None


CGM_RANGE_CONFIG = CGMSectionConfig(
    name="cgm_range_stats",
    keys=[
        "below_54_percent",
        "below_70_above_54_percent",
        "in_target_70_180_percent",
        "above_180_below_250_percent",
        "above_250_percent",
    ],
    template_method="cgm_range_stats",
    call_signature="stats",
)

CGM_SUMMARY_CONFIG = CGMSectionConfig(
    name="cgm_summary_stats",
    keys=[
        "average_glucose_mgdl",
        "gmi",
        "gmi_mmol",
        "glucose_variability_percent",
        "coefficient_of_variation_percent",
        "std_dev_glucose_mgdl",
        "highest_glucose_mgdl",
        "highest_glucose_date",
        "lowest_glucose_mgdl",
        "lowest_glucose_date",
    ],
    template_method="cgm_summary_stats",
    call_signature="stats",
)

HYPER_STATS_CONFIG = CGMSectionConfig(
    name="hyper_stats",
    keys=[
        "total_hyper_duration_minutes",
        "hyper_events_count",
        "average_hyper_duration_minutes",
    ],
    template_method="hyper_stats",
    call_signature="stats",
)

HYPO_STATS_CONFIG = CGMSectionConfig(
    name="hypo_stats",
    keys=[
        "total_hypo_duration_minutes",
        "hypo_events_count",
        "average_hypo_duration_minutes",
    ],
    template_method="hypo_stats",
    call_signature="stats",
)

RAPID_SPIKE_STATS_CONFIG = CGMSectionConfig(
    name="rapid_spike_stats",
    keys=[
        "total_spike_duration_minutes",
        "average_spike_duration_minutes",
        "spike_events_count",
    ],
    template_method="rapid_spike_stats",
    call_signature="stats",
)

RAPID_DROP_STATS_CONFIG = CGMSectionConfig(
    name="rapid_drop_stats",
    keys=[
        "total_drop_duration_minutes",
        "average_drop_duration_minutes",
        "drop_events_count",
    ],
    template_method="rapid_drop_stats",
    call_signature="stats",
)

CGM_SEMANTIC_WINDOW_CONFIG = CGMSectionConfig(
    name="cgm_semantic_window",
    keys=[
        "readings_count",
        "min_glucose_mgdl",
        "avg_glucose_mgdl",
        "max_glucose_mgdl",
    ],
    template_method="cgm_semantic_window",
    call_signature="stats",
)

# Event configurations
HYPER_EVENT_CONFIG = CGMSectionConfig(
    name="hyper_event",
    keys=["start_time", "end_time", "duration_minutes", "peak_glucose_mgdl"],
    template_method="hyper_event",
    call_signature="event",
)

HYPO_EVENT_CONFIG = CGMSectionConfig(
    name="hypo_event",
    keys=["start_time", "end_time", "duration_minutes", "lowest_glucose_mgdl"],
    template_method="hypo_event",
    call_signature="event",
)

RAPID_SPIKE_EVENT_CONFIG = CGMSectionConfig(
    name="rapid_spike_event",
    keys=[
        "start_time",
        "end_time",
        "duration_minutes",
        "initial_glucose_mgdl",
        "peak_glucose_mgdl",
        "peak_glucose_time",
    ],
    template_method="rapid_spike_event",
    call_signature="event",
)

RAPID_DROP_EVENT_CONFIG = CGMSectionConfig(
    name="rapid_drop_event",
    keys=[
        "start_time",
        "end_time",
        "duration_minutes",
        "initial_glucose_mgdl",
        "lowest_glucose_mgdl",
        "lowest_glucose_time",
    ],
    template_method="rapid_drop_event",
    call_signature="event",
)


# Unified configuration mapping
CGM_SECTION_CONFIGS = {
    # Statistics sections
    "cgm_range_stats": CGM_RANGE_CONFIG,
    "cgm_summary_stats": CGM_SUMMARY_CONFIG,
    "hyper_stats": HYPER_STATS_CONFIG,
    "hypo_stats": HYPO_STATS_CONFIG,
    "rapid_spike_stats": RAPID_SPIKE_STATS_CONFIG,
    "rapid_drop_stats": RAPID_DROP_STATS_CONFIG,
    "cgm_semantic_window": CGM_SEMANTIC_WINDOW_CONFIG,
    # Event sections
    "hyper_event": HYPER_EVENT_CONFIG,
    "hypo_event": HYPO_EVENT_CONFIG,
    "rapid_spike_event": RAPID_SPIKE_EVENT_CONFIG,
    "rapid_drop_event": RAPID_DROP_EVENT_CONFIG,
}

STATS_CONFIGS = {
    name: config
    for name, config in CGM_SECTION_CONFIGS.items()
    if config.call_signature == "stats"
}

EVENT_CONFIGS = {
    name: config
    for name, config in CGM_SECTION_CONFIGS.items()
    if config.call_signature == "event"
}


# Utility functions
def get_section_config(section_name: str) -> Optional[CGMSectionConfig]:
    """Get configuration for a specific section by name."""
    return CGM_SECTION_CONFIGS.get(section_name)


def get_stats_configs() -> Dict[str, CGMSectionConfig]:
    """Get all statistics configurations."""
    return STATS_CONFIGS


def get_event_configs() -> Dict[str, CGMSectionConfig]:
    """Get all event configurations."""
    return EVENT_CONFIGS


def get_all_section_names() -> List[str]:
    """Get all available section names."""
    return list(CGM_SECTION_CONFIGS.keys())


def get_stats_section_names() -> List[str]:
    """Get all statistics section names."""
    return list(STATS_CONFIGS.keys())


def get_event_section_names() -> List[str]:
    """Get all event section names."""
    return list(EVENT_CONFIGS.keys())
