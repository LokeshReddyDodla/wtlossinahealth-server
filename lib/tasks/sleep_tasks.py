from datetime import datetime

from celery import shared_task

from lib.utils.async_runner import run_async_task
from lib.utils.date_utils import get_month_start_end, get_months_between_dates
from lib.utils.sleep.sleep_stats_processor import SleepReportType


@shared_task
def generate_sleep_reports_for_patient(
    patient_id: str, start_date: datetime, end_date: datetime
):
    from lib.dependencies.service_dependencies import get_celery_task_manager

    try:
        task_manager = get_celery_task_manager()
        months_between = get_months_between_dates(start_date, end_date)

        for year, month in reversed(months_between):
            month_start_date, month_end_date = get_month_start_end(year, month)

            task_manager.trigger_task_once(
                "lib.tasks.sleep_tasks.generate_sleep_report_for_month",
                args=[
                    patient_id,
                    month_start_date,
                    month_end_date,
                ],
                task_id=f"{patient_id}_{month_start_date}_{month_end_date}_{SleepReportType.MONTHLY}",
            )

        print(f"Generated sleep report for patient: {patient_id}")
    except Exception as e:
        print(f"Failed to generate sleep report for {patient_id}. Error: {e}")


@shared_task
async def generate_sleep_report_for_month(
    patient_id: str, start_date: datetime, end_date: datetime
):
    try:
        from lib.dependencies.service_dependencies import (
            get_sleep_report_service,
            get_sleep_stats_processor,
        )

        processor = get_sleep_stats_processor()
        service = get_sleep_report_service()

        reports = await processor.generate_report(
            patient_id,
            start_date,
            end_date,
            report_types=[
                SleepReportType.MONTHLY,
                SleepReportType.WEEKLY,
                SleepReportType.DAILY,
            ],
        )

        # Bulk save
        await service.save_reports_bulk(patient_id, reports)

        print(
            f"✅ Generated sleep report for {patient_id} from {start_date}-{end_date}"
        )
    except Exception as e:
        print(
            f"❌ Failed to generate sleep report for {patient_id} from {start_date}-{end_date}. Error: {e}"
        )


@shared_task
async def generate_sleep_report(
    patient_id: str,
    start_date: datetime,
    end_date: datetime,
    report_type: str,
):
    try:
        from lib.dependencies.service_dependencies import (
            get_sleep_report_service,
            get_sleep_stats_processor,
        )

        processor = get_sleep_stats_processor()
        service = get_sleep_report_service()

        report_types = []
        if report_type in [
            SleepReportType.WEEKLY,
            SleepReportType.MONTHLY,
        ]:
            report_types = [report_type, SleepReportType.DAILY]
        else:
            report_types = [report_type]

        reports = await processor.generate_report(
            patient_id, start_date, end_date, report_types=report_types
        )

        # Bulk save
        await service.save_reports_bulk(patient_id, reports)

        print(
            f"✅ Generated {report_type} sleep report for {patient_id} from {start_date} to {end_date}"
        )

    except Exception as e:
        print(
            f"❌ Failed to generate {report_type} report for {patient_id} from {start_date} to {end_date}. Error: {e}"
        )
