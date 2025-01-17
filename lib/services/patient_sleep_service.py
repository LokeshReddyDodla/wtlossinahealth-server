from datetime import date, datetime, time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.models.patient_sleep import PatientSleep as PatientSleepModel
from lib.services.patient_profile_service import PatientProfileService


class PatientSleepService:
    def __init__(
        self,
        patient_profile_service: PatientProfileService,
        postgres_session: AsyncSession,
    ):
        self.postgres_session = postgres_session
        self.patient_profile_service = patient_profile_service

    async def get_daily_report_in_range(
        self, patient_id: str, start_datetime: datetime, end_datetime: datetime
    ):
        query = text(
            """
            SELECT jsonb_object_agg(sleep_date, records) AS grouped_data
            FROM (
                SELECT 
                    DATE(ps.sleep_start_time) AS sleep_date,
                    JSON_AGG(
                        JSON_BUILD_OBJECT(
                            'id', ps.id,
                            'type', ps.type,
                            'sleep_duration', ps.sleep_duration,
                            'sleep_start_time', ps.sleep_start_time,
                            'sleep_end_time', ps.sleep_end_time,
                            'uploaded_at', ps.uploaded_at
                        )
                    ) AS records
                FROM patient_sleeps ps
                WHERE ps.patient_id = :patient_id
                AND ps.sleep_start_time >= :start_datetime
                AND ps.sleep_end_time <= :end_datetime
                GROUP BY sleep_date
                ORDER BY sleep_date
            ) AS subquery
        """
        )

        result = await self.postgres_session.execute(
            query,
            {
                "patient_id": patient_id,
                "start_datetime": start_datetime,
                "end_datetime": end_datetime,
            },
        )

        grouped_data = result.scalar()
        return grouped_data

    async def get_daily_sleep_data(self, patient_id: str, date: date):
        start_datetime = datetime.combine(date, time.min)
        end_datetime = datetime.combine(date, time.max).replace(microsecond=0)

        query = text(
            """
            SELECT jsonb_object_agg(sleep_type, records) AS grouped_data
            FROM (
                SELECT 
                    ps.type AS sleep_type,
                    JSON_AGG(
                        JSON_BUILD_OBJECT(
                            'id', ps.id,
                            'type', ps.type,
                            'sleep_duration', ps.sleep_duration,
                            'sleep_start_time', ps.sleep_start_time,
                            'sleep_end_time', ps.sleep_end_time,
                            'uploaded_at', ps.uploaded_at
                        )
                    ) AS records
                FROM patient_sleeps ps
                WHERE ps.patient_id = :patient_id
                AND ps.sleep_start_time >= :start_datetime
                AND ps.sleep_end_time <= :end_datetime
                GROUP BY ps.type
                ORDER BY ps.type
            ) AS subquery
        """
        )

        result = await self.postgres_session.execute(
            query,
            {
                "patient_id": patient_id,
                "start_datetime": start_datetime,
                "end_datetime": end_datetime,
            },
        )

        grouped_data = result.scalar()
        return grouped_data
