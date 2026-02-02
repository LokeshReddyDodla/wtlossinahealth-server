"""Database query utilities for SMBG data."""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.models.patient_smbg import PatientSMBG


class SMBGQueries:
    """Database query utilities for SMBG records."""

    @staticmethod
    async def fetch_readings_in_range(
        postgres_session: AsyncSession,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> List[PatientSMBG]:
        """
        Fetch SMBG readings within a date range.

        Args:
            postgres_session: Database session
            patient_id: Patient identifier
            start_date: Start datetime (inclusive)
            end_date: End datetime (inclusive)

        Returns:
            List of PatientSMBG records
        """
        result = await postgres_session.execute(
            select(PatientSMBG)
            .where(PatientSMBG.patient_id == patient_id)
            .where(PatientSMBG.reading_time >= start_date)
            .where(PatientSMBG.reading_time <= end_date)
        )
        return list(result.scalars().all())

    @staticmethod
    async def fetch_readings_for_previous_week(
        postgres_session: AsyncSession,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        offset_days: int = 7,
    ) -> List[PatientSMBG]:
        """
        Fetch SMBG readings from the previous week.

        Args:
            postgres_session: Database session
            patient_id: Patient identifier
            start_date: Current period start date
            end_date: Current period end date
            offset_days: Number of days to offset (default: 7)

        Returns:
            List of PatientSMBG records from previous week
        """
        from datetime import timedelta

        prev_start = start_date - timedelta(days=offset_days)
        prev_end = end_date - timedelta(days=offset_days)

        return await SMBGQueries.fetch_readings_in_range(
            postgres_session, patient_id, prev_start, prev_end
        )

    @staticmethod
    def filter_by_type(
        records: List[PatientSMBG], meal_types: tuple
    ) -> List[PatientSMBG]:
        """
        Filter records by meal type.

        Args:
            records: List of PatientSMBG records
            meal_types: Tuple of meal type strings to filter

        Returns:
            Filtered list of records
        """
        return [r for r in records if r.type in meal_types]

    @staticmethod
    def filter_by_date_range(
        records: List[PatientSMBG],
        start_date: datetime,
        end_date: datetime,
    ) -> List[PatientSMBG]:
        """
        Filter records by date range.

        Args:
            records: List of PatientSMBG records
            start_date: Start datetime (inclusive)
            end_date: End datetime (inclusive)

        Returns:
            Filtered list of records
        """
        return [
            r
            for r in records
            if start_date <= r.reading_time <= end_date
        ]
