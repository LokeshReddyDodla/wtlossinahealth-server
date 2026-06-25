"""Constants for SMBG report processing."""

from typing import Dict, Tuple

VALID_SMBG_TYPES = ("fasting", "before_meal", "after_meal", "random")

MEAL_WINDOWS: Dict[str, Tuple[int, int]] = {
    "breakfast": (4, 11),
    "lunch": (11, 16),
    "dinner": (17, 3),
}

GLUCOSE_RANGE_LOW = 70
GLUCOSE_RANGE_HIGH = 180

PRE_MEAL_TYPES = ("before_meal",)
POST_MEAL_TYPES = ("after_meal",)
FASTING_TYPE = "fasting"
RANDOM_TYPE = "random"

BUCKET_NAMES = [
    "fasting",
    "pre_breakfast",
    "post_breakfast",
    "pre_lunch",
    "post_lunch",
    "pre_dinner",
    "post_dinner",
    "random",
]

PREVIOUS_WEEK_OFFSET_DAYS = 7
