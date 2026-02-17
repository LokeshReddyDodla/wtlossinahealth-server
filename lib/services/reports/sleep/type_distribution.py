from datetime import datetime
from typing import Dict, Union

from sqlalchemy import func, select

from lib.models.patient_sleep import PatientSleep


class SleepTypeDistributionStatistics:
    @staticmethod
    async def fetch(
        postgres_session,
        patient_id: str,
        start_datetime: datetime,
        end_datetime: datetime,
    ) -> Dict[str, Union[Dict[str, float], float]]:
        days_diff = (end_datetime - start_datetime).days + 1

        query = (
            select(
                PatientSleep.type,
                func.sum(PatientSleep.sleep_duration).label("duration"),
            )
            .where(
                PatientSleep.patient_id == patient_id,
                PatientSleep.sleep_start_time >= start_datetime,
                PatientSleep.sleep_end_time <= end_datetime,
            )
            .group_by(PatientSleep.type)
        )
        result = await postgres_session.execute(query)
        rows = result.fetchall()

        total_duration = sum(row.duration for row in rows)

        distribution = {
            row.type: {
                "duration_minutes": row.duration,
                "percentage": (
                    (row.duration / total_duration) * 100
                    if total_duration
                    else 0
                ),
                "per_day_average_minutes": (
                    row.duration / days_diff if days_diff > 0 else 0
                ),
            }
            for row in rows
        }

        return {
            "total_duration": total_duration,
            "per_day_average_total": (
                total_duration / days_diff if days_diff > 0 else 0
            ),
            "distribution": distribution,
        }
