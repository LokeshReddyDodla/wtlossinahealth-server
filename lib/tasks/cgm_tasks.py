import asyncio
from datetime import date, datetime
from typing import Any, Dict, List, Tuple, cast

from celery import shared_task

from lib.services.cgm_report_service import CGMReportService
from lib.services.meal_report_service import MealReportService
from lib.utils.glucose.processor import GlucoseStatsProcessor
from lib.utils.meals.processor import MealStatsProcessor


@shared_task
def generate_cgm_reports_for_patient(
    patient_id: str, periods: List[Tuple[str, str]]
):
    from lib.dependencies.service_dependencies import get_celery_task_manager

    try:
        task_manager = get_celery_task_manager()
        for start_date, end_date in reversed(periods):
            task_manager.trigger_task_once(
                "lib.tasks.cgm_tasks.generate_cgm_report",
                args=[patient_id, start_date, end_date],
                task_id=f"{patient_id}_{start_date}_{end_date}",
            )

            print(
                f"✅ Triggered CGM report task for {patient_id} ({start_date} - {end_date})"
            )

    except Exception as e:
        print(
            f"❌ Failed to generate CGM reports for {patient_id}. Error: {e}"
        )


@shared_task
def generate_cgm_report(
    patient_id: str,
    start_date: datetime,
    end_date: datetime,
):
    try:
        from lib.dependencies.service_dependencies import (
            get_cgm_report_service, get_glucose_stats_processor)

        glucose_stats_service = get_glucose_stats_processor()
        cgm_report_service = get_cgm_report_service()

        async def generate_and_save_report():
            report = await glucose_stats_service.generate_report(
                patient_id, start_date, end_date
            )

            await cgm_report_service.save_report(
                patient_id,
                {
                    "patient_id": patient_id,
                    "start_date": start_date,
                    "end_date": end_date,
                    **report,
                },
            )

        loop = asyncio.get_event_loop()
        loop.run_until_complete(generate_and_save_report())

        print(
            f"✅ Successfully generated cgm report for {patient_id} from {start_date} to {end_date}."
        )

    except Exception as error:
        print(
            f"❌ Failed to generate cgm report for {patient_id} from {start_date} to {end_date}. Error: {error}"
        )
