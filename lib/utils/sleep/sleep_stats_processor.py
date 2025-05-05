from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

from lib.schemas.sleep_stats import SleepStats
from lib.services.ai_conversation_service.ai_conversation_service import (
    AiConversationService,
)
from lib.utils.date.periods import DayWisePeriod, WeekWisePeriod
from lib.utils.sleep.duration_fetcher import SleepDurationFetcher
from lib.utils.sleep.quality_fetcher import SleepQualityFetcher
from lib.utils.sleep.timing_fetcher import SleepTimingFetcher
from lib.utils.sleep.type_distribution_fetcher import SleepTypeDistributionFetcher


class SleepStatsProcessor:
    def __init__(self, postgres_session: AsyncSession):
        self.postgres_session = postgres_session
        self.ai_conversation_service = AiConversationService(
            conversation_type="sleep",
            selected_ai_model="gpt-4o-mini",
            ai_model_provider="openai",
        )

    async def generate_report(
        self,
        patient_id: str,
        start_datetime: datetime,
        end_datetime: datetime,
        include_overall: bool = True,
        include_day_wise: bool = True,
        include_week_wise: bool = True,
    ) -> Dict[str, Any]:
        report = {}

        # Overall Stats
        if include_overall:
            report["overall"] = await self._process_overall(
                patient_id, start_datetime, end_datetime
            )

        # Day-wise Stats
        if include_day_wise:
            day_periods = DayWisePeriod(start_datetime, end_datetime).periods
            report["day_wise"] = await self._process_multiple_periods(
                patient_id, day_periods
            )

        # Week-wise Stats
        if include_week_wise:
            week_periods = WeekWisePeriod(start_datetime, end_datetime).periods
            report["week_wise"] = await self._process_multiple_periods(
                patient_id, week_periods
            )

        return report

    async def _process_overall(
        self, patient_id: str, start_datetime: datetime, end_datetime: datetime
    ) -> SleepStats:
        duration_analysis = await SleepDurationFetcher.fetch(
            self.postgres_session, patient_id, start_datetime, end_datetime
        )
        type_distribution = await SleepTypeDistributionFetcher.fetch(
            self.postgres_session, patient_id, start_datetime, end_datetime
        )
        timing_analysis = await SleepTimingFetcher.fetch(
            self.postgres_session, patient_id, start_datetime, end_datetime
        )  # Inaccurate
        quality_analysis = await SleepQualityFetcher.fetch(
            self.postgres_session, patient_id, start_datetime, end_datetime
        )

        # Construct the sleep stats report
        report = SleepStats(
            start_date=start_datetime,
            end_date=end_datetime,
            duration_analysis=duration_analysis,
            type_distribution=type_distribution,
            timing_analysis=timing_analysis,
            quality_analysis=quality_analysis,
        )

        return report

    async def _process_multiple_periods(
        self, patient_id: str, periods: List[Dict[str, datetime]]
    ) -> List[Dict[str, SleepStats]]:
        stats = []
        for period in periods:
            stats.append(
                await self._process_overall(
                    patient_id,
                    period["start_date"],
                    period["end_date"],
                )
            )
        return stats
