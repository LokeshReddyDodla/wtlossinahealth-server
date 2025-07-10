import asyncio
from datetime import datetime

from celery import shared_task

from lib.core.types import SleepReportTypeLiteral
from lib.utils.async_runner import run_async_task
from lib.utils.date_utils import get_month_start_end, get_months_between_dates


@shared_task
def generate_sleep_reports_for_patient(
    patient_id: str, start_date: datetime, end_date: datetime
):
    from lib.dependencies.service_dependencies import get_celery_task_manager

    try:
        task_manager = get_celery_task_manager()
        months_between = get_months_between_dates(start_date, end_date)
        report_type: SleepReportTypeLiteral = "monthly"

        for year, month in reversed(months_between):
            month_start_date, month_end_date = get_month_start_end(year, month)

            task_manager.trigger_task_once(
                "lib.tasks.sleep_tasks.generate_sleep_report_for_month",
                args=[
                    patient_id,
                    month_start_date,
                    month_end_date,
                ],
                task_id=f"{patient_id}_{month_start_date}_{month_end_date}_{report_type}",
            )

        print(f"Generated sleep report for patient: {patient_id}")
    except Exception as e:
        print(f"Failed to generate sleep report for {patient_id}. Error: {e}")


@shared_task
def generate_sleep_report_for_month(
    patient_id: str, start_date: datetime, end_date: datetime
):
    try:
        from lib.dependencies.service_dependencies import (
            get_sleep_report_service,
            get_sleep_stats_processor,
        )

        sleep_stats_service = get_sleep_stats_processor()
        sleep_report_service = get_sleep_report_service()
        # ai_conversation_service = get_ai_conversation_service()

        async def generate_and_save_report():
            # Generate report for the specific month
            report = await sleep_stats_service.generate_report(
                patient_id,
                start_date,
                end_date,
                include_overall=True,
                include_week_wise=True,
                include_day_wise=True,
            )

            # Generate AI feedback based on the sleep report
            # feedback_message = await ai_conversation_service.generate_report_response(
            #     patient_id,
            #     patient_id,
            #     report,
            #     "sleep",
            # )

            # Prepare reports for bulk saving
            bulk_reports = []
            bulk_reports.append(
                {
                    "patient_id": patient_id,
                    "report_type": "monthly",
                    # "feedback": feedback_message,
                    **report["overall"].model_dump(),
                }
            )
            bulk_reports.extend(
                [
                    {
                        "patient_id": patient_id,
                        "report_type": "weekly",
                        **week_stat.model_dump(),
                    }
                    for week_stat in report["week_wise"]
                ]
            )
            bulk_reports.extend(
                [
                    {
                        "patient_id": patient_id,
                        "report_type": "daily",
                        **day_stat.model_dump(),
                    }
                    for day_stat in report["day_wise"]
                ]
            )

            await sleep_report_service.save_reports_bulk(bulk_reports)

        # Save reports
        loop = asyncio.get_event_loop()
        loop.run_until_complete(generate_and_save_report())

        print(
            f"✅ Generated sleep report for {patient_id} from {start_date}-{end_date}"
        )
    except Exception as e:
        print(
            f"❌ Failed to generate sleep report for {patient_id} from {start_date}-{end_date}. Error: {e}"
        )


@shared_task
def generate_sleep_report(
    patient_id: str,
    start_date: datetime,
    end_date: datetime,
    report_type: SleepReportTypeLiteral,
):
    try:
        from lib.dependencies.service_dependencies import (
            get_sleep_report_service,
            get_sleep_stats_processor,
        )

        sleep_stats_service = get_sleep_stats_processor()
        sleep_report_service = get_sleep_report_service()
        # ai_conversation_service = get_ai_conversation_service()

        async def generate_and_save_report():
            report = await sleep_stats_service.generate_report(
                patient_id,
                start_date,
                end_date,
                include_overall=True,
                include_day_wise=report_type in ["weekly", "monthly"],
            )

            # AI feedback
            # feedback_message = await ai_conversation_service.generate_report_response(
            #     patient_id,
            #     patient_id,
            #     report,
            #     "sleep",
            # )

            bulk_reports = []
            bulk_reports.append(
                {
                    "patient_id": patient_id,
                    "report_type": report_type,
                    # "feedback": feedback_message,
                    **report["overall"].model_dump(),
                }
            )
            if report_type in ["weekly", "monthly"]:
                bulk_reports.extend(
                    [
                        {
                            "patient_id": patient_id,
                            "report_type": "daily",
                            **day_stat.model_dump(),
                        }
                        for day_stat in report["day_wise"]
                    ]
                )

            await sleep_report_service.save_reports_bulk(bulk_reports)

        # Save reports
        loop = asyncio.get_event_loop()
        loop.run_until_complete(generate_and_save_report())

        print(
            f"✅ Generated {report_type} sleep report for {patient_id} from {start_date} to {end_date}"
        )

    except Exception as e:
        print(
            f"❌ Failed to generate {report_type} report for {patient_id} from {start_date} to {end_date}. Error: {e}"
        )
