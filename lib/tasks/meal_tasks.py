import asyncio
from datetime import date

from celery import shared_task

from lib.utils.async_runner import (
    run_async_blocking,
    run_async_in_thread,
    run_async_task,
)


@shared_task
def generate_daily_meal_report(
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

        async def generate_and_save_report():
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

        run_async_in_thread(generate_and_save_report())

        print(
            f"✅ Successfully generated meal report for {patient_id} on {report_date}"
        )

    except Exception as error:
        print(
            f"❌ Failed to generate meal report for {patient_id} on {report_date}. Error: {error}"
        )
