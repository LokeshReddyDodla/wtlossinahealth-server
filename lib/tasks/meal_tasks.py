import asyncio
from datetime import date, datetime, time
from typing import cast

from asgiref.sync import async_to_sync
from celery import shared_task

from lib.services.meal_report_service import MealReportService
from lib.utils.meals.processor import MealStatsProcessor


@shared_task
def generate_daily_meal_report(
    patient_id: str,
    report_date: date,
):
    try:
        from lib.core.container import container

        meal_stats_service = cast(
            MealStatsProcessor, container.resolve(MealStatsProcessor)
        )
        meal_report_service = cast(
            MealReportService, container.resolve(MealReportService)
        )

        report = async_to_sync(meal_stats_service.get_meal_report_by_date)(
            patient_id, report_date
        )

        meal_report_service.save_report(
            patient_id,
            {
                "patient_id": patient_id,
                "report_type": "daily",
                **report.model_dump(),
            },
        )

        print(
            f"✅ Successfully generated meal report for {patient_id} on {report_date}"
        )

    except Exception as error:
        print(
            f"❌ Failed to generate meal report for {patient_id} on {report_date}. Error: {error}"
        )
