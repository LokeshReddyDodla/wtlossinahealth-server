from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import func, select

from lib.models.patient_sleep import PatientSleep
from lib.services.ai_conversation_service import AiConversationService
from lib.utils.date.periods import DayWisePeriod, WeekWisePeriod
from lib.utils.sleep.duration_fetcher import SleepDurationFetcher
from lib.utils.sleep.quality_fetcher import SleepQualityFetcher
from lib.utils.sleep.timing_fetcher import SleepTimingFetcher
from lib.utils.sleep.type_distribution_fetcher import \
    SleepTypeDistributionFetcher


class SleepStatsProcessor:
    def __init__(self, postgres_session):
        self.postgres_session = postgres_session
        self.ai_conversation_service = AiConversationService(
            conversation_type="sleep", model="gpt-4o-mini"
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
    ) -> Dict[str, Any]:

        report = {
            "start_datetime": start_datetime,
            "end_datetime": end_datetime,
            "duration_analysis": await SleepDurationFetcher.fetch(
                self.postgres_session, patient_id, start_datetime, end_datetime
            ),
            "type_distribution": await SleepTypeDistributionFetcher.fetch(
                self.postgres_session, patient_id, start_datetime, end_datetime
            ),
            "timing_analysis": await SleepTimingFetcher.fetch(
                self.postgres_session, patient_id, start_datetime, end_datetime
            ),  # not accurate!
            "quality_analysis": await SleepQualityFetcher.fetch(
                self.postgres_session, patient_id, start_datetime, end_datetime
            ),
        }

        # Generate feedback based on the sleep report
        feedback_message = (
            await self.ai_conversation_service.generate_report_response(
                patient_id, report, "sleep"
            )
        )

        # Add the feedback to the report
        report["feedback"] = feedback_message

        # message_content = f"""
        #     ### Sleep Feedback Report
        #     **Date Range:** {start_datetime.strftime('%Y-%m-%d')} to {end_datetime.strftime('%Y-%m-%d')}

        #     **Feedback:**
        #     {feedback_message}
        # """

        # # Add feedback message to the conversation
        # await self.ai_conversation_service.add_message_to_conversation(
        #     patient_id=patient_id,
        #     conversation_id=f"{patient_id}-custom",
        #     conversation_type="sleep",
        #     role="ai",
        #     content=message_content,
        #     message_type="markdown",
        #     exclude_from_frontend=True,
        # )

        return report

    async def _process_multiple_periods(
        self, patient_id: str, periods: List[Dict[str, datetime]]
    ) -> List[Dict[str, Any]]:
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
