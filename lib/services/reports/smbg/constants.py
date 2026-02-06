"""Constants for SMBG report processing."""

from typing import Dict, Tuple

MEAL_WINDOWS: Dict[str, Tuple[int, int]] = {
    "breakfast": (4, 11),
    "lunch": (11, 16),
    "dinner": (17, 3),
}

GLUCOSE_RANGE_LOW = 70
GLUCOSE_RANGE_HIGH = 180

PRE_MEAL_TYPES = ("before_meal", "pre_meal")
POST_MEAL_TYPES = ("after_meal", "post_meal")

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

PREVIOUS_WEEK_OFFSET_DAYS = 7
