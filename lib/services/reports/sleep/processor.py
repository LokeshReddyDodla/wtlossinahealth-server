from datetime import datetime
from typing import List

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore
from lib.models.patient_sleep import PatientSleep
from lib.schemas.sleep_stats import (
    DateRange,
    ReportMetadata,
    SleepDuration,
    SleepQuality,
    SleepStats,
    SleepTiming,
    SleepTypeDistribution,
)
from lib.utils.date.periods import DayWisePeriod, WeekWisePeriod
from lib.utils.postgres_session_decorator import with_postgres_session

from .duration import SleepDurationStatistics
from .quality import SleepQualityStatistics
from .timing import SleepTimingStatistics
from .type_distribution import SleepTypeDistributionStatistics


class SleepReportType:
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"


class SleepStatsProcessor:
    def __init__(self, postgres_store: PostgresStore):
        self.postgres_store = postgres_store

    async def generate_report(
        self,
        patient_id: str,
        start_datetime: datetime,
        end_datetime: datetime,
        report_types: List[str] = [
            SleepReportType.MONTHLY,
            SleepReportType.DAILY,
            SleepReportType.WEEKLY,
        ],
    ) -> List[SleepStats]:
        reports: List[SleepStats] = []

        if SleepReportType.MONTHLY in report_types:
            reports.append(
                await self._process_period(
                    patient_id,
                    start_datetime,
                    end_datetime,
                    SleepReportType.MONTHLY,
                )
            )

        if SleepReportType.WEEKLY in report_types:
            week_periods = WeekWisePeriod(start_datetime, end_datetime).periods
            reports.extend(
                await self._process_multiple_periods(
                    patient_id, week_periods, SleepReportType.WEEKLY
                )
            )

        if SleepReportType.DAILY in report_types:
            day_periods = DayWisePeriod(start_datetime, end_datetime).periods
            reports.extend(
                await self._process_multiple_periods(
                    patient_id, day_periods, SleepReportType.DAILY
                )
            )

        return reports

    @with_postgres_session
    async def _process_period(
        self,
        patient_id: str,
        start_datetime: datetime,
        end_datetime: datetime,
        report_type: str,
        *,
        postgres_session: AsyncSession,
    ) -> SleepStats:
        days_covered = (end_datetime - start_datetime).days + 1

        total_sessions_query = select(func.count(PatientSleep.id)).where(
            PatientSleep.patient_id == patient_id,
            PatientSleep.sleep_start_time >= start_datetime,
            PatientSleep.sleep_end_time <= end_datetime,
        )
        total_sessions_result = await postgres_session.execute(total_sessions_query)
        total_sessions = total_sessions_result.scalar() or 0

        duration_data = await SleepDurationStatistics.fetch(
            postgres_session, patient_id, start_datetime, end_datetime
        )
        type_distribution_data = await SleepTypeDistributionStatistics.fetch(
            postgres_session, patient_id, start_datetime, end_datetime
        )
        timing_data = await SleepTimingStatistics.fetch(
            postgres_session, patient_id, start_datetime, end_datetime
        )
        quality_data = await SleepQualityStatistics.fetch(
            postgres_session, patient_id, start_datetime, end_datetime
        )

        return SleepStats(
            metadata=ReportMetadata(
                date_range=DateRange(
                    start=start_datetime.isoformat(),
                    end=end_datetime.isoformat(),
                ),
                total_sessions=total_sessions,
                days_covered=days_covered,
                report_type=report_type,
            ),
            duration=SleepDuration(**duration_data),
            type_distribution=SleepTypeDistribution(**type_distribution_data),
            timing=SleepTiming(**timing_data),
            quality=SleepQuality(**quality_data),
        )

    @with_postgres_session
    async def _process_multiple_periods(
        self,
        patient_id: str,
        periods: List[dict],
        report_type: str,
        *,
        postgres_session: AsyncSession,
    ) -> List[SleepStats]:
        stats = []
        for period in periods:
            stats.append(
                await self._process_period(
                    patient_id,
                    period["start_date"],
                    period["end_date"],
                    report_type,
                    postgres_session=postgres_session,
                )
            )
        return stats
