from datetime import datetime

from celery import shared_task

from lib.utils.date_utils import get_month_start_end, get_months_between_dates
from lib.utils.fitness.processor import FitnessReportType


@shared_task(queue="default")
def trigger_fitness_report_generation_for_patient(
    patient_id: str, start_date: datetime, end_date: datetime
):
    from lib.dependencies.service_dependencies import get_celery_task_manager

    try:
        task_manager = get_celery_task_manager()
        months_between = get_months_between_dates(start_date, end_date)

        print(f"🏃 Triggering fitness reports for patient: {patient_id}")

        for year, month in reversed(months_between):
            month_start, month_end = get_month_start_end(year, month)

            task_manager.trigger_task_once(
                "lib.tasks.fitness_tasks.generate_and_store_fitness_report_for_month",
                args=[
                    patient_id,
                    month_start,
                    month_end,
                ],
                task_id=f"{patient_id}_{month_start}_{month_end}_{FitnessReportType.MONTHLY}",
                queue="default",
            )

        print(
            f"📅 Queued monthly fitness report for {patient_id} "
            f"({month_start.isoformat()} - {month_end.isoformat()})"
        )
    except Exception as e:
        print(
            f"❌ Failed triggering fitness reports for {patient_id}. Error: {e}"
        )


@shared_task(queue="default")
async def generate_and_store_fitness_report_for_month(
    patient_id: str, start_date: datetime, end_date: datetime
):
    try:

        from lib.dependencies.service_dependencies import (
            get_fitness_report_service,
            get_fitness_stats_processor,
        )

        processor = get_fitness_stats_processor()
        service = get_fitness_report_service()

        reports = processor.generate_report(
            patient_id,
            start_date,
            end_date,
            report_types=[
                FitnessReportType.MONTHLY,
                FitnessReportType.WEEKLY,
                FitnessReportType.DAILY,
            ],
        )

        # Bulk save
        await service.save_reports_bulk(patient_id, reports)

        print(
            f"✅ Monthly fitness report saved for {patient_id} "
            f"({start_date.isoformat()} – {end_date.isoformat()})"
        )
    except Exception as e:
        print(
            f"❌ Failed monthly fitness report for {patient_id} "
            f"({start_date.isoformat()} – {end_date.isoformat()}). Error: {e}"
        )


@shared_task(queue="default")
async def generate_and_store_fitness_report(
    patient_id: str,
    start_date: datetime,
    end_date: datetime,
    report_type: str,
):
    try:
        from lib.dependencies.service_dependencies import (
            get_fitness_report_service,
            get_fitness_stats_processor,
        )

        processor = get_fitness_stats_processor()
        service = get_fitness_report_service()

        report_types = []
        if report_type in [
            FitnessReportType.WEEKLY,
            FitnessReportType.MONTHLY,
        ]:
            report_types = [report_type, FitnessReportType.DAILY]
        else:
            report_types = [report_type]

        reports = processor.generate_report(
            patient_id, start_date, end_date, report_types=report_types
        )

        # Bulk save
        await service.save_reports_bulk(patient_id, reports)

        print(
            f"✅ Generated {report_type} fitness report for {patient_id} "
            f"({start_date.isoformat()} – {end_date.isoformat()})"
        )
    except Exception as e:
        print(
            f"❌ Failed {report_type} fitness report for {patient_id} "
            f"({start_date.isoformat()} – {end_date.isoformat()}). Error: {e}"
        )
