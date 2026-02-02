"""Statistics calculation utilities for SMBG data."""

import statistics
from datetime import datetime
from typing import List, Optional

from lib.models.patient_smbg import PatientSMBG
from .constants import GLUCOSE_RANGE_LOW, GLUCOSE_RANGE_HIGH


class SMBGStatistics:
    """Statistics calculation utilities for SMBG readings."""

    @staticmethod
    def calculate_basic_stats(
        readings: List[PatientSMBG],
    ) -> dict:
        """
        Calculate basic statistics for a list of SMBG readings.

        Args:
            readings: List of PatientSMBG records

        Returns:
            Dictionary with count, out_of_range, highest, lowest, median
        """
        if not readings:
            return {
                "count": 0,
                "out_of_range": 0,
                "highest": None,
                "lowest": None,
                "median": None,
            }

        levels = [r.glucose_level for r in readings]

        return {
            "count": len(levels),
            "out_of_range": sum(
                1 for level in levels if not SMBGStatistics.is_in_range(level)
            ),
            "highest": max(levels),
            "lowest": min(levels),
            "median": statistics.median(levels),
        }

    @staticmethod
    def calculate_window_stats(
        readings: List[PatientSMBG],
    ) -> dict:
        """
        Calculate statistics for a meal window including average time.

        Args:
            readings: List of PatientSMBG records

        Returns:
            Dictionary with window statistics including average_time
        """
        if not readings:
            return {
                "count": 0,
                "out_of_range": 0,
                "highest": None,
                "lowest": None,
                "median": None,
                "average_time": None,
            }

        levels = [r.glucose_level for r in readings]
        times = [r.reading_time for r in readings]

        stats = SMBGStatistics.calculate_basic_stats(readings)
        stats["average_time"] = SMBGStatistics.average_time(times)

        return stats

    @staticmethod
    def calculate_summary_stats(
        pre_meal_readings: List[PatientSMBG],
        post_meal_readings: List[PatientSMBG],
    ) -> dict:
        """
        Calculate summary statistics for pre and post meal readings.

        Args:
            pre_meal_readings: List of pre-meal SMBG records
            post_meal_readings: List of post-meal SMBG records

        Returns:
            Dictionary with pre_meal, post_meal, and overall stats
        """
        def summarize(readings: List[PatientSMBG]) -> dict:
            if not readings:
                return {
                    "count": 0,
                    "within_range": 0,
                    "within_range_pct": 0.0,
                }

            count = len(readings)
            within_range = sum(
                1
                for r in readings
                if SMBGStatistics.is_in_range(r.glucose_level)
            )

            return {
                "count": count,
                "within_range": within_range,
                "within_range_pct": round(within_range * 100 / count, 1),
            }

        pre_stats = summarize(pre_meal_readings)
        post_stats = summarize(post_meal_readings)

        total_count = pre_stats["count"] + post_stats["count"]
        total_within_range = pre_stats["within_range"] + post_stats["within_range"]

        return {
            "pre_meal": pre_stats,
            "post_meal": post_stats,
            "score": {
                "pre_meal": pre_stats["within_range_pct"],
                "post_meal": post_stats["within_range_pct"],
                "overall": round(
                    total_within_range * 100 / max(1, total_count), 1
                ),
            },
        }

    @staticmethod
    def is_in_range(
        value: float, low: float = GLUCOSE_RANGE_LOW, high: float = GLUCOSE_RANGE_HIGH
    ) -> bool:
        """
        Check if glucose value is within target range.

        Args:
            value: Glucose level in mg/dL
            low: Lower bound (default: 70)
            high: Upper bound (default: 180)

        Returns:
            True if value is within range
        """
        return low <= value <= high

    @staticmethod
    def average_time(datetimes: List[datetime]) -> Optional[str]:
        """
        Compute average time of day from a list of datetimes.

        Args:
            datetimes: List of datetime objects

        Returns:
            Average time as 'HH:MM' string, or None if empty
        """
        if not datetimes:
            return None

        total_seconds = [
            dt.hour * 3600 + dt.minute * 60 + dt.second for dt in datetimes
        ]
        avg_seconds = sum(total_seconds) / len(total_seconds)
        hours, remainder = divmod(int(avg_seconds), 3600)
        minutes, _ = divmod(remainder, 60)

        return f"{hours:02d}:{minutes:02d}"

    @staticmethod
    def calculate_median(values: List[float]) -> Optional[float]:
        """
        Calculate median of a list of values.

        Args:
            values: List of numeric values

        Returns:
            Median value or None if empty
        """
        if not values:
            return None
        return statistics.median(values)
