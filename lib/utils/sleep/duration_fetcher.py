from datetime import datetime
from typing import Any, Dict

from sqlalchemy import func, select

from lib.models.patient_sleep import PatientSleep


class SleepDurationFetcher:
    @staticmethod
    async def fetch(
        postgres_session,
        patient_id: str,
        start_datetime: datetime,
        end_datetime: datetime,
    ) -> Dict[str, Any]:
        days_diff = (end_datetime - start_datetime).days + 1

        query = select(
            func.sum(PatientSleep.sleep_duration).label("total_duration"),
            func.avg(PatientSleep.sleep_duration).label("avg_duration"),
            func.max(PatientSleep.sleep_duration).label("max_duration"),
            func.min(PatientSleep.sleep_duration).label("min_duration"),
        ).where(
            PatientSleep.patient_id == patient_id,
            PatientSleep.sleep_start_time >= start_datetime,
            PatientSleep.sleep_end_time <= end_datetime,
        )
        result = await postgres_session.execute(query)
        row = result.first()

        # Calculate per-day averages
        total_duration = row.total_duration or 0
        per_day_avg_duration = (
            total_duration / days_diff if days_diff > 0 else 0
        )

        return {
            "total_duration": row.total_duration,
            "average_duration": row.avg_duration,
            "per_day_average_duration": per_day_avg_duration,
            "longest_sleep": row.max_duration,
            "shortest_sleep": row.min_duration,
        }
