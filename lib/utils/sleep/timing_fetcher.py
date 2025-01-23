from datetime import datetime, time, timedelta
from typing import Any, Dict

from sqlalchemy import text

from lib.models.patient_sleep import PatientSleep


class SleepTimingFetcher:
    @staticmethod
    async def fetch(
        postgres_session,
        patient_id: str,
        start_datetime: datetime,
        end_datetime: datetime,
    ) -> Dict[str, Any]:
        query = text(
            """
        SELECT 
            MIN(sleep_start_time::time) AS earliest_start,
            MAX(sleep_end_time::time) AS latest_end,
            AVG(sleep_start_time::time) AS avg_start,
            AVG(sleep_end_time::time) AS avg_end
        FROM 
            patient_sleeps
        WHERE 
            patient_id = :patient_id
            AND sleep_start_time >= :start_datetime
            AND sleep_end_time <= :end_datetime
            AND (
                sleep_start_time::time >= '18:00' OR sleep_end_time::time < '12:00'
            )
            AND type != 'sleep_awake'
        """
        )

        # Execute the query
        result = await postgres_session.execute(
            query,
            {
                "patient_id": patient_id,
                "start_datetime": start_datetime,
                "end_datetime": end_datetime,
            },
        )
        row = result.first()

        # Return results as ISO 8601 formatted strings
        return {
            "earliest_start_time": (
                row.earliest_start if row.earliest_start else None
            ),
            "latest_end_time": (row.latest_end if row.latest_end else None),
            "average_start_time": (row.avg_start if row.avg_start else None),
            "average_end_time": (row.avg_end if row.avg_end else None),
        }
