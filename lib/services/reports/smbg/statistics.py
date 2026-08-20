"""Statistics calculation utilities for SMBG data."""

import math
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
        """Calculate basic statistics for a list of SMBG readings."""
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
        """Calculate statistics for a meal window including average time."""
        if not readings:
            return {
                "count": 0,
                "out_of_range": 0,
                "highest": None,
                "lowest": None,
                "median": None,
                "average_time": None,
            }

        times = [r.reading_time for r in readings]

        stats = SMBGStatistics.calculate_basic_stats(readings)
        stats["average_time"] = SMBGStatistics.average_time(times)

        return stats

    @staticmethod
    def calculate_summary_stats(
        fasting_readings: List[PatientSMBG],
        pre_meal_readings: List[PatientSMBG],
        post_meal_readings: List[PatientSMBG],
        random_readings: List[PatientSMBG],
    ) -> dict:
        """Calculate summary statistics for all reading types."""
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

        fasting_stats = summarize(fasting_readings)
        pre_stats = summarize(pre_meal_readings)
        post_stats = summarize(post_meal_readings)
        random_stats = summarize(random_readings)

        all_groups = [fasting_stats, pre_stats, post_stats, random_stats]
        total_count = sum(g["count"] for g in all_groups)
        total_within_range = sum(g["within_range"] for g in all_groups)

        return {
            "fasting": fasting_stats,
            "pre_meal": pre_stats,
            "post_meal": post_stats,
            "random": random_stats,
            "score": {
                "fasting": fasting_stats["within_range_pct"],
                "pre_meal": pre_stats["within_range_pct"],
                "post_meal": post_stats["within_range_pct"],
                "random": random_stats["within_range_pct"],
                "overall": round(
                    total_within_range * 100 / max(1, total_count), 1
                ),
            },
        }

    @staticmethod
    def is_in_range(
        value: float, low: float = GLUCOSE_RANGE_LOW, high: float = GLUCOSE_RANGE_HIGH
    ) -> bool:
        """Check if glucose value is within target range."""
        return low <= value <= high

    @staticmethod
    def average_time(datetimes: List[datetime]) -> Optional[str]:
        """Circular mean of clock times — a linear mean puts 23:30 + 00:30 at
        12:00, and the dinner meal window wraps midnight."""
        if not datetimes:
            return None

        angles = [
            (dt.hour * 3600 + dt.minute * 60 + dt.second) / 86400 * 2 * math.pi
            for dt in datetimes
        ]
        mean_angle = math.atan2(
            sum(math.sin(a) for a in angles) / len(angles),
            sum(math.cos(a) for a in angles) / len(angles),
        )
        # float % can round up to exactly 86400; the int modulo makes midnight 0
        avg_seconds = round(mean_angle / (2 * math.pi) * 86400) % 86400
        hours, remainder = divmod(int(avg_seconds), 3600)
        minutes, _ = divmod(remainder, 60)

        return f"{hours:02d}:{minutes:02d}"

    @staticmethod
    def calculate_median(values: List[float]) -> Optional[float]:
        """Calculate median of a list of values."""
        if not values:
            return None
        return statistics.median(values)
