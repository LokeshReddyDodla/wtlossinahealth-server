import calendar
from datetime import datetime, timedelta
import statistics
from typing import Any, Optional
from sqlalchemy import select

from lib.models.patient_smbg import PatientSMBG
from lib.utils.date.periods import WeekWisePeriod
from lib.utils.postgres_session_decorator import with_postgres_session

WINDOWS = {
    "breakfast": (5, 11),  # 05:00–10:59
    "lunch": (12, 16),  # 12:00–15:59
    "dinner": (19, 23),  # 19:00–22:59
}


class SMBGStatsProcessor:
    def __init__(
        self,
        postgres_store,
        patient_profile_service,
        patient_plan_service,
        meal_stats_processor,
    ):
        self.postgres_store = postgres_store
        self.patient_profile_service = patient_profile_service
        self.patient_plan_service = patient_plan_service
        self.meal_stats_processor = meal_stats_processor

    @with_postgres_session
    async def get_stats(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        *,
        postgres_session,
    ):
        # fetch SMBGs in range
        result = await postgres_session.execute(
            select(PatientSMBG)
            .where(PatientSMBG.patient_id == patient_id)
            .where(PatientSMBG.reading_time >= start_date)
            .where(PatientSMBG.reading_time <= end_date)
        )
        smbg_records = result.scalars().all()

        if not smbg_records:
            return {}

        # classify readings into meal windows
        buckets = self._bucketize_by_meal(smbg_records)

        stats: dict[str, Any] = {
            "start_date": start_date,
            "end_date": end_date,
            "meal_windows": {},
        }

        for bucket_name, readings in buckets.items():
            levels = [r.glucose_level for r in readings]
            if not levels:
                continue

            avg_time = self._average_time([r.reading_time for r in readings])

            stats["meal_windows"][bucket_name] = {
                "count": len(levels),
                "out_of_range": sum(
                    1 for v in levels if not self._is_in_range(v)
                ),
                "highest": max(levels),
                "lowest": min(levels),
                "median": statistics.median(levels),
                "average_time": avg_time,
                "median_prev_week": await self._median_previous_week(
                    patient_id, start_date, end_date, bucket_name
                ),
            }

        # add overall median vs previous week median
        all_levels = [r.glucose_level for r in smbg_records]
        stats["overall"] = {
            "count": len(all_levels),
            "out_of_range": sum(
                1 for v in all_levels if not self._is_in_range(v)
            ),
            "highest": max(all_levels),
            "lowest": min(all_levels),
            "median": statistics.median(all_levels),
            "average_time": self._average_time(
                [r.reading_time for r in smbg_records]
            ),
            "median_prev_week": await self._median_previous_week(
                patient_id, start_date, end_date
            ),
            "meal_statistics": await self.meal_stats_processor.get_meal_statistics_in_range(
                patient_id, start_date, end_date
            ),
        }

        # month summary
        month_start = datetime(start_date.year, start_date.month, 1)
        last_day = calendar.monthrange(start_date.year, start_date.month)[1]
        month_end = datetime(
            start_date.year, start_date.month, last_day, 23, 59, 59
        )

        stats["month_summary"] = {
            "start_date": month_start,
            "end_date": month_end,
            "smbg": await self.get_monthly_summary(
                patient_id=patient_id,
                start_date=month_start,
                end_date=month_end,
                postgres_session=postgres_session,
            ),  # type: ignore
            "meal": await self.meal_stats_processor.get_meal_month_summary(
                patient_id=patient_id,
                start_date=month_start,
                end_date=month_end,
            ),
        }

        return stats

    @with_postgres_session
    async def get_monthly_summary(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        *,
        postgres_session,
    ):
        result = await postgres_session.execute(
            select(PatientSMBG)
            .where(PatientSMBG.patient_id == patient_id)
            .where(PatientSMBG.reading_time >= start_date)
            .where(PatientSMBG.reading_time <= end_date)
        )
        smbg_records = result.scalars().all()

        if not smbg_records:
            return {}

        # Split pre vs post
        pre_meal = [
            r for r in smbg_records if r.type in ("before_meal", "pre_meal")
        ]
        post_meal = [
            r for r in smbg_records if r.type in ("after_meal", "post_meal")
        ]

        # Counts + within range
        def summarize(readings):
            if not readings:
                return {"count": 0, "within_range": 0, "within_range_pct": 0.0}
            count = len(readings)
            within = sum(
                1 for r in readings if self._is_in_range(r.glucose_level)
            )
            return {
                "count": count,
                "within_range": within,
                "within_range_pct": round(within * 100 / count, 1),
            }

        pre_stats = summarize(pre_meal)
        post_stats = summarize(post_meal)

        # Trend per week
        weeks = WeekWisePeriod(start_date, end_date).periods
        trend = {}
        current = start_date
        for week in weeks:
            week_start = week["start_date"]
            week_end = week["end_date"]
            week_no = week["week_no"]
            iso_week_no = week["iso_week_no"]

            week_records = [
                r
                for r in smbg_records
                if current <= r.reading_time <= week_end
            ]

            pre_week = [
                r.glucose_level
                for r in week_records
                if r.type in ("before_meal", "pre_meal")
            ]
            post_week = [
                r.glucose_level
                for r in week_records
                if r.type in ("after_meal", "post_meal")
            ]

            trend[f"week_{week_no}"] = {
                "pre_meal_median": (
                    statistics.median(pre_week) if pre_week else None
                ),
                "post_meal_median": (
                    statistics.median(post_week) if post_week else None
                ),
                "start_date": week_start,
                "end_date": week_end,
                "iso_week_no": iso_week_no,
            }
            current = week_end + timedelta(days=1)

        return {
            "total_smbg": len(smbg_records),
            "pre_meal": pre_stats,
            "post_meal": post_stats,
            "score": {
                "pre_meal": pre_stats["within_range_pct"],
                "post_meal": post_stats["within_range_pct"],
                "overall": round(
                    (pre_stats["within_range"] + post_stats["within_range"])
                    * 100
                    / max(1, (pre_stats["count"] + post_stats["count"])),
                    1,
                ),
            },
            "trend": trend,
        }

    def _bucketize_by_meal(self, records):
        buckets = {
            "pre_breakfast": [],
            "post_breakfast": [],
            "pre_lunch": [],
            "post_lunch": [],
            "pre_dinner": [],
            "post_dinner": [],
            "random": [],
            "other": [],
        }

        for r in records:
            hour = r.reading_time.hour

            for meal, (start, end) in WINDOWS.items():
                if start <= hour <= end:
                    if r.type in ("before_meal", "pre_meal"):
                        buckets[f"pre_{meal}"].append(r)
                    elif r.type in ("after_meal", "post_meal"):
                        buckets[f"post_{meal}"].append(r)
                    else:
                        buckets["random"].append(r)
                    break
            else:
                buckets["other"].append(r)

        return buckets

    @with_postgres_session
    async def _median_previous_week(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        bucket_name: Optional[str] = None,
        *,
        postgres_session,
    ):
        prev_start = start_date - timedelta(days=7)
        prev_end = end_date - timedelta(days=7)

        result = await postgres_session.execute(
            select(PatientSMBG)
            .where(PatientSMBG.patient_id == patient_id)
            .where(PatientSMBG.reading_time >= prev_start)
            .where(PatientSMBG.reading_time <= prev_end)
        )
        records = result.scalars().all()
        if not records:
            return None

        if bucket_name:
            buckets = self._bucketize_by_meal(records)
            values = [r.glucose_level for r in buckets[bucket_name]]
        else:
            values = [r.glucose_level for r in records]

        return statistics.median(values) if values else None

    def _average_time(self, datetimes: list[datetime]) -> Optional[str]:
        """Compute average time of day from a list of datetimes, return 'HH:MM'."""
        if not datetimes:
            return None
        total_seconds = [
            dt.hour * 3600 + dt.minute * 60 + dt.second for dt in datetimes
        ]
        avg_seconds = sum(total_seconds) / len(total_seconds)
        hours, remainder = divmod(int(avg_seconds), 3600)
        minutes, _ = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}"

    def _is_in_range(self, value: float, low=70, high=180):
        return low <= value <= high
