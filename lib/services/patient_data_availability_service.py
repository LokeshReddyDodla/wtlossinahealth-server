from datetime import date, datetime, timedelta
from typing import Dict

from sqlalchemy import and_, cast, Date, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.clickhouse_store import ClickHouseStore
from lib.core.postgres_store import PostgresStore
from lib.models.patient_meal import PatientMeal
from lib.models.patient_smbg import PatientSMBG
from lib.models.patient_vital import PatientVital
from lib.schemas.patient_data_availability import (
    DateDataAvailability,
    PatientDataAvailabilityResponse,
)
from lib.utils.postgres_session_decorator import with_postgres_session


class PatientDataAvailabilityService:
    """Service to check data availability for a patient across date ranges"""

    def __init__(
        self,
        postgres_store: PostgresStore,
        clickhouse_store: ClickHouseStore,
    ):
        self.postgres_store = postgres_store
        self.clickhouse_store = clickhouse_store

    @with_postgres_session
    async def get_data_availability(
        self,
        patient_id: str,
        target_date: date,
        days_before: int = 5,
        days_after: int = 5,
        *,
        postgres_session: AsyncSession,
    ) -> PatientDataAvailabilityResponse:
        # Calculate date range
        start_date = target_date - timedelta(days=days_before)
        end_date = target_date + timedelta(days=days_after)

        # Initialize all dates with zero counts
        date_range = []
        current_date = start_date
        while current_date <= end_date:
            date_range.append(current_date)
            current_date += timedelta(days=1)

        # Query all data sources
        smbg_counts = await self._get_smbg_counts(
            patient_id, start_date, end_date, postgres_session
        )
        meal_counts = await self._get_meal_counts(
            patient_id, start_date, end_date, postgres_session
        )
        vitals_counts = await self._get_vitals_counts(
            patient_id, start_date, end_date, postgres_session
        )
        cgm_counts = await self._get_cgm_counts(patient_id, start_date, end_date)
        fitness_counts = await self._get_fitness_counts(
            patient_id, start_date, end_date
        )

        # Build response
        availability_list = []
        for dt in date_range:
            smbg_count = smbg_counts.get(dt, 0)
            meal_count = meal_counts.get(dt, 0)
            vitals_count = vitals_counts.get(dt, 0)
            cgm_count = cgm_counts.get(dt, 0)
            fitness_count = fitness_counts.get(dt, 0)

            availability_list.append(
                DateDataAvailability(
                    date=dt,
                    smbg_count=smbg_count,
                    meal_count=meal_count,
                    fitness_count=fitness_count,
                    cgm_count=cgm_count,
                    vitals_count=vitals_count,
                    has_smbg=smbg_count > 0,
                    has_meal=meal_count > 0,
                    has_fitness=fitness_count > 0,
                    has_cgm=cgm_count > 0,
                    has_vitals=vitals_count > 0,
                )
            )

        return PatientDataAvailabilityResponse(
            patient_id=patient_id,
            target_date=target_date,
            availability=availability_list,
        )

    async def _get_smbg_counts(
        self,
        patient_id: str,
        start_date: date,
        end_date: date,
        session: AsyncSession,
    ) -> Dict[date, int]:
        """Get SMBG reading counts grouped by date"""
        query = select(
            cast(PatientSMBG.reading_time, Date).label("date"),
            func.count(PatientSMBG.id).label("count"),
        ).where(
            and_(
                PatientSMBG.patient_id == patient_id,
                cast(PatientSMBG.reading_time, Date) >= start_date,
                cast(PatientSMBG.reading_time, Date) <= end_date,
            )
        ).group_by(cast(PatientSMBG.reading_time, Date))

        result = await session.execute(query)
        rows = result.fetchall()
        return {row[0]: row[1] for row in rows}

    async def _get_meal_counts(
        self,
        patient_id: str,
        start_date: date,
        end_date: date,
        session: AsyncSession,
    ) -> Dict[date, int]:
        """Get meal counts grouped by date"""
        query = select(
            PatientMeal.date,
            func.count(PatientMeal.id).label("count"),
        ).where(
            and_(
                PatientMeal.patient_id == patient_id,
                PatientMeal.date >= start_date,
                PatientMeal.date <= end_date,
            )
        ).group_by(PatientMeal.date)

        result = await session.execute(query)
        rows = result.fetchall()
        return {row[0]: row[1] for row in rows}

    async def _get_vitals_counts(
        self,
        patient_id: str,
        start_date: date,
        end_date: date,
        session: AsyncSession,
    ) -> Dict[date, int]:
        """Get vitals counts grouped by date"""
        query = select(
            cast(PatientVital.test_time, Date).label("date"),
            func.count(PatientVital.id).label("count"),
        ).where(
            and_(
                PatientVital.patient_id == patient_id,
                cast(PatientVital.test_time, Date) >= start_date,
                cast(PatientVital.test_time, Date) <= end_date,
            )
        ).group_by(cast(PatientVital.test_time, Date))

        result = await session.execute(query)
        rows = result.fetchall()
        return {row[0]: row[1] for row in rows}

    async def _get_cgm_counts(
        self,
        patient_id: str,
        start_date: date,
        end_date: date,
    ) -> Dict[date, int]:
        """Get CGM data counts grouped by date from ClickHouse"""
        try:
            # Convert dates to datetime for ClickHouse query
            start_datetime = datetime.combine(start_date, datetime.min.time())
            end_datetime = datetime.combine(
                end_date, datetime.max.time().replace(microsecond=0)
            )

            query = f"""
            SELECT 
                toDate(time) as date,
                count(*) as count
            FROM aihealth.cgm_data
            WHERE patient_id = '{patient_id}'
                AND time >= '{start_datetime.strftime('%Y-%m-%d %H:%M:%S')}'
                AND time <= '{end_datetime.strftime('%Y-%m-%d %H:%M:%S')}'
            GROUP BY toDate(time)
            """

            result = self.clickhouse_store.client.execute(query)
            if result:
                return {row[0]: row[1] for row in result}  # type: ignore
            return {}
        except Exception as e:
            # Log error and return empty dict
            print(f"Error fetching CGM counts: {e}")
            return {}

    async def _get_fitness_counts(
        self,
        patient_id: str,
        start_date: date,
        end_date: date,
    ) -> Dict[date, int]:
        """Get fitness data counts grouped by date from ClickHouse"""
        try:
            # Convert dates to datetime for ClickHouse query
            start_datetime = datetime.combine(start_date, datetime.min.time())
            end_datetime = datetime.combine(
                end_date, datetime.max.time().replace(microsecond=0)
            )

            query = f"""
            SELECT 
                toDate(start_datetime) as date,
                count(*) as count
            FROM aihealth.fitness_data
            WHERE patient_id = '{patient_id}'
                AND start_datetime >= '{start_datetime.strftime('%Y-%m-%d %H:%M:%S')}'
                AND start_datetime <= '{end_datetime.strftime('%Y-%m-%d %H:%M:%S')}'
            GROUP BY toDate(start_datetime)
            """

            result = self.clickhouse_store.client.execute(query)
            if result:
                return {row[0]: row[1] for row in result}  # type: ignore
            return {}
        except Exception as e:
            # Log error and return empty dict
            print(f"Error fetching fitness counts: {e}")
            return {}
