import asyncio
from datetime import datetime
from typing import List, Tuple

from celery import shared_task

from lib.utils.async_runner import run_async_task


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
            get_cgm_report_service,
            get_cgm_stats_processor,
        )

        cgm_stats_service = get_cgm_stats_processor()
        cgm_report_service = get_cgm_report_service()
        # ai_conversation_service = get_ai_conversation_service()

        async def generate_and_save_report():
            report = await cgm_stats_service.generate_report(
                patient_id, start_date, end_date
            )
            # feedback_message = await ai_conversation_service.generate_report_response(
            #     patient_id,
            #     patient_id,
            #     report,
            #     "cgm",
            # )

            await cgm_report_service.save_report(
                patient_id,
                {
                    "patient_id": patient_id,
                    "start_date": start_date,
                    "end_date": end_date,
                    # "feedback": feedback_message,
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
