import asyncio
from datetime import date

from celery import shared_task


@shared_task
async def generate_daily_meal_report(
    patient_id: str,
    report_date: date,
):
    try:
        from lib.dependencies.service_dependencies import (
            get_meal_report_service,
            get_meal_stats_processor,
        )

        processor = get_meal_stats_processor()
        service = get_meal_report_service()

        # Generate the meal report
        report = await processor.get_meal_report_by_date(
            patient_id, report_date
        )

        # Save the meal report
        await service.save_report(
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
