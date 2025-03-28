import asyncio
from datetime import date
from typing import cast

from celery import shared_task


@shared_task
def generate_daily_meal_report(
    patient_id: str,
    report_date: date,
):
    try:
        from lib.dependencies.service_dependencies import (
            get_meal_report_service, get_meal_stats_processor)

        meal_stats_service = get_meal_stats_processor()
        meal_report_service = get_meal_report_service()

        async def generate_and_save_report():
            # Generate the meal report
            report = await meal_stats_service.get_meal_report_by_date(
                patient_id, report_date
            )

            # Save the meal report
            await meal_report_service.save_report(
                patient_id,
                {
                    "patient_id": patient_id,
                    "report_type": "daily",
                    **report.model_dump(),
                },
            )

        loop = asyncio.get_event_loop()
        loop.run_until_complete(generate_and_save_report())

        print(
            f"✅ Successfully generated meal report for {patient_id} on {report_date}"
        )

    except Exception as error:
        print(
            f"❌ Failed to generate meal report for {patient_id} on {report_date}. Error: {error}"
        )
