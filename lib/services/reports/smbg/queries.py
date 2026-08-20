"""Database query utilities for SMBG data."""

from datetime import datetime
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.models.patient_smbg import PatientSMBG
from .constants import VALID_SMBG_TYPES


class SMBGQueries:
    """Database query utilities for SMBG records."""

    @staticmethod
    async def fetch_readings_in_range(
        postgres_session: AsyncSession,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> List[PatientSMBG]:
        """Fetch SMBG readings within a date range. Device-synced rows carry
        non-canonical types (HealthKit has no meal context) — they are read
        and normalized to "random" here so every downstream grouper sees only
        canonical types."""
        result = await postgres_session.execute(
            select(PatientSMBG)
            .where(PatientSMBG.patient_id == patient_id)
            .where(PatientSMBG.reading_time >= start_date)
            .where(PatientSMBG.reading_time <= end_date)
        )
        records = list(result.scalars().all())
        for r in records:
            if r.type not in VALID_SMBG_TYPES:
                r.type = "random"
        return records

    @staticmethod
    def filter_by_type(
        records: List[PatientSMBG], meal_types: tuple
    ) -> List[PatientSMBG]:
        """Filter records by meal type."""
        return [r for r in records if r.type in meal_types]

    @staticmethod
    def filter_by_date_range(
        records: List[PatientSMBG],
        start_date: datetime,
        end_date: datetime,
    ) -> List[PatientSMBG]:
        """Filter records by date range."""
        return [
            r
            for r in records
            if start_date <= r.reading_time <= end_date
        ]
