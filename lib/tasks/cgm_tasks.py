import asyncio
from datetime import date, datetime
from typing import cast

from celery import shared_task

from lib.services.cgm_report_service import CGMReportService
from lib.services.meal_report_service import MealReportService
from lib.utils.glucose.processor import GlucoseStatsProcessor
from lib.utils.meals.processor import MealStatsProcessor


@shared_task
def generate_cgm_report(
    patient_id: str,
    start_date: datetime,
    end_date: datetime,
):
    try:
        from lib.core.container import container

        glucose_stats_service = cast(
            GlucoseStatsProcessor, container.resolve(GlucoseStatsProcessor)
        )
        cgm_report_service = cast(
            CGMReportService, container.resolve(CGMReportService)
        )

        report = glucose_stats_service.generate_report(
            patient_id, start_date, end_date
        )

        # meal_report_service.save_report(
        #     patient_id,
        #     {
        #         "patient_id": patient_id,
        #         "report_type": "daily",
        #         **report.model_dump(),
        #     },
        # )

        # print(
        #     f"✅ Successfully generated meal report for {patient_id} on {report_date}"
        # )

    except Exception as error:
        pass
        # print(
        #     f"❌ Failed to generate meal report for {patient_id} on {report_date}. Error: {error}"
        # )
