"""Constants for vector services."""

# Default configuration
DEFAULT_CHUNK_SIZE = 200
DEFAULT_COLLECTION_NAME = "patient_data"

# Time bucket definitions
TIME_BUCKETS = {
    "morning": (6, 12),
    "afternoon": (12, 18),
    "evening": (18, 24),
    "night": (0, 6),
}

# Data type constants
DATA_TYPE_CGM = "cgm"
DATA_TYPE_FITNESS = "fitness"
DATA_TYPE_MEAL = "meal"
DATA_TYPE_SMBG = "smbg"
DATA_TYPE_PROFILE = "profile"
DATA_TYPE_VITAL = "vital"

# Common data type prefixes
DATA_TYPE_PREFIXES = {
    "cgm_range_stats",
    "cgm_summary_stats",
    "hyper_stats",
    "hypo_stats",
    "rapid_spike_stats",
    "rapid_drop_stats",
    "hyper_event",
    "hypo_event",
    "rapid_spike_event",
    "rapid_drop_event",
    "time_period_stats",
    "agp_point",
    "cgm_semantic_window",
    "fitness_overview",
    "fitness_activity_distribution",
    "fitness_inactive_periods",
    "meal",
    "smbg",
    "profile",
    "vital",
}
