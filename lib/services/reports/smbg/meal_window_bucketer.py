"""Meal window bucketing logic for SMBG readings."""

from typing import Dict, List

from lib.models.patient_smbg import PatientSMBG
from .constants import (
    MEAL_WINDOWS,
    PRE_MEAL_TYPES,
    POST_MEAL_TYPES,
    BUCKET_NAMES,
)


class MealWindowBucketer:
    """Handles bucketing of SMBG readings into meal time windows."""

    @staticmethod
    def bucketize_by_meal(records: List[PatientSMBG]) -> Dict[str, List[PatientSMBG]]:
        """Classify SMBG readings into meal time windows."""
        buckets: Dict[str, List[PatientSMBG]] = {
            bucket_name: [] for bucket_name in BUCKET_NAMES
        }

        for record in records:
            hour = record.reading_time.hour
            assigned = False

            for meal_name, (start_hour, end_hour) in MEAL_WINDOWS.items():
                if MealWindowBucketer._is_in_window(hour, start_hour, end_hour):
                    bucket_name = MealWindowBucketer._get_bucket_name(
                        meal_name, record.type
                    )
                    buckets[bucket_name].append(record)
                    assigned = True
                    break

            if not assigned:
                buckets["other"].append(record)

        return buckets

    @staticmethod
    def _is_in_window(hour: int, start_hour: int, end_hour: int) -> bool:
        """Check if an hour falls within a time window."""
        if start_hour < end_hour:
            return start_hour <= hour < end_hour
        else:
            return hour >= start_hour or hour < end_hour

    @staticmethod
    def _get_bucket_name(meal_name: str, reading_type: str) -> str:
        """Get bucket name based on meal and reading type."""
        if reading_type in PRE_MEAL_TYPES:
            return f"pre_{meal_name}"
        elif reading_type in POST_MEAL_TYPES:
            return f"post_{meal_name}"
        else:
            return "random"

    @staticmethod
    def filter_by_bucket(
        records: List[PatientSMBG], bucket_name: str
    ) -> List[PatientSMBG]:
        """Filter records for a specific bucket."""
        buckets = MealWindowBucketer.bucketize_by_meal(records)
        return buckets.get(bucket_name, [])
