from datetime import date, datetime, time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.core.postgres_store import PostgresStore
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.postgres_session_decorator import with_postgres_session


class PatientSleepService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        patient_profile_service: PatientProfileService,
    ):
        self.postgres_store = postgres_store
        self.patient_profile_service = patient_profile_service

    @with_postgres_session
    async def get_daily_report_in_range(
        self,
        patient_id: str,
        start_datetime: datetime,
        end_datetime: datetime,
        *,
        postgres_session: AsyncSession
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

        result = await postgres_session.execute(
            query,
            {
                "patient_id": patient_id,
                "start_datetime": start_datetime,
                "end_datetime": end_datetime,
            },
        )

        grouped_data = result.scalar()
        return grouped_data

    @with_postgres_session
    async def get_daily_sleep_data(
        self, patient_id: str, date: date, *, postgres_session: AsyncSession
    ):
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

        result = await postgres_session.execute(
            query,
            {
                "patient_id": patient_id,
                "start_datetime": start_datetime,
                "end_datetime": end_datetime,
            },
        )

        grouped_data = result.scalar()
        return grouped_data
