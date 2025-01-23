from datetime import datetime
from typing import Any, Dict

from sqlalchemy import func, select

from lib.models.patient_sleep import PatientSleep


class SleepQualityFetcher:
    @staticmethod
    async def fetch(
        postgres_session,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> Dict[str, Any]:
        query = (
            select(
                PatientSleep.type,
                func.sum(PatientSleep.sleep_duration).label("duration"),
            )
            .where(
                PatientSleep.patient_id == patient_id,
                PatientSleep.sleep_start_time >= start_date,
                PatientSleep.sleep_end_time <= end_date,
            )
            .group_by(PatientSleep.type)
        )
        result = await postgres_session.execute(query)
        rows = result.fetchall()

        total_duration = sum(
            row.duration
            for row in rows
            if row.type in ("sleep_deep", "sleep_light", "sleep_rem")
        )
        in_bed_duration = next(
            (row.duration for row in rows if row.type == "sleep_in_bed"), None
        )
        deep_sleep = next(
            (row.duration for row in rows if row.type == "sleep_deep"), 0
        )
        rem_sleep = next(
            (row.duration for row in rows if row.type == "sleep_rem"), 0
        )
        awake_time = next(
            (row.duration for row in rows if row.type == "sleep_awake"), 0
        )

        # Fallback to total sleep duration if `sleep_in_bed` is not available
        effective_in_bed_duration = in_bed_duration or (
            total_duration + awake_time
        )

        sleep_efficiency = (
            (total_duration / effective_in_bed_duration) * 100
            if effective_in_bed_duration > 0
            else 0
        )
        restorative_sleep = (
            ((deep_sleep + rem_sleep) / total_duration) * 100
            if total_duration > 0
            else 0
        )
        awake_percentage = (
            (awake_time / effective_in_bed_duration) * 100
            if effective_in_bed_duration > 0
            else 0
        )

        sleep_quality = SleepQualityFetcher._classify_sleep_quality(
            sleep_efficiency, restorative_sleep, awake_percentage
        )

        return {
            "deep_sleep_percentage": (
                (deep_sleep / total_duration) * 100 if total_duration else 0
            ),
            "rem_sleep_percentage": (
                (rem_sleep / total_duration) * 100 if total_duration else 0
            ),
            "awake_time_percentage": awake_percentage,
            "restorative_sleep": restorative_sleep,
            "sleep_efficiency": sleep_efficiency,
            "sleep_quality": sleep_quality,
        }

    @staticmethod
    def _classify_sleep_quality(
        sleep_efficiency: float,
        restorative_sleep: float,
        awake_percentage: float,
    ) -> str:
        if (
            sleep_efficiency >= 90
            and restorative_sleep >= 60
            and awake_percentage < 5
        ):
            return "excellent"
        elif (
            sleep_efficiency >= 85
            and restorative_sleep >= 50
            and awake_percentage < 10
        ):
            return "good"
        elif (
            sleep_efficiency >= 75
            and restorative_sleep >= 40
            and awake_percentage < 15
        ):
            return "could be better"
        elif (
            sleep_efficiency >= 60
            and restorative_sleep >= 30
            and awake_percentage < 20
        ):
            return "poor"
        else:
            return "very poor"
