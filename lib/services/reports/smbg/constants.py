"""Constants for SMBG report processing."""

from typing import Dict, Tuple

# Meal time windows: (start_hour, end_hour)
# Note: end_hour can be less than start_hour for overnight periods
MEAL_WINDOWS: Dict[str, Tuple[int, int]] = {
    "breakfast": (4, 11),   # 04:00–10:59
    "lunch": (11, 16),      # 11:00–15:59
    "dinner": (17, 3),      # 17:00–03:59 (overnight)
}

# Glucose range thresholds (mg/dL)
GLUCOSE_RANGE_LOW = 70
GLUCOSE_RANGE_HIGH = 180

# Meal type mappings
PRE_MEAL_TYPES = ("before_meal", "pre_meal")
POST_MEAL_TYPES = ("after_meal", "post_meal")

# Bucket names for meal windows
BUCKET_NAMES = [
    "pre_breakfast",
    "post_breakfast",
    "pre_lunch",
    "post_lunch",
    "pre_dinner",
    "post_dinner",
    "random",
    "other",
]

# Previous week offset (days)
PREVIOUS_WEEK_OFFSET_DAYS = 7
