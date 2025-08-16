from datetime import datetime
from typing import List, Tuple

from celery import shared_task


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
async def generate_cgm_report(
    patient_id: str,
    start_date: datetime,
    end_date: datetime,
):
    try:
        from lib.dependencies.service_dependencies import (
            get_cgm_report_service,
            get_cgm_stats_processor,
        )

        processor = get_cgm_stats_processor()
        service = get_cgm_report_service()
        reports = await processor.generate_report(
            patient_id, start_date, end_date
        )

        # Bulk save
        await service.save_reports_bulk(patient_id, reports)

        print(
            f"✅ Successfully generated CGM report for {patient_id} from {start_date} to {end_date}."
        )

    except Exception as error:
        print(
            f"❌ Failed to generate CGM report for {patient_id} from {start_date} to {end_date}. Error: {error}"
        )
