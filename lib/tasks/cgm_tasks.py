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
        if not reports:
            print(
                f"⚠️ No CGM reports generated for {patient_id} ({start_date} - {end_date})"
            )
            return

        report_id = await service.save_reports_bulk(patient_id, reports)
        if not report_id:
            print(f"❌ Failed to save CGM reports for {patient_id}")
            return

        day_wise_reports = await service.fetch_day_wise_reports(
            patient_id, start_date, end_date
        )
        if not day_wise_reports:
            print(f"⚠️ No day-wise CGM reports found for {patient_id}")
            return

        generate_cgm_vector.delay(patient_id, report_id, day_wise_reports)

        print(
            f"✅ Successfully generated CGM report for {patient_id} from {start_date} to {end_date}."
        )

    except Exception as error:
        print(
            f"❌ Failed to generate CGM report for {patient_id} from {start_date} to {end_date}. Error: {error}"
        )


@shared_task
async def generate_cgm_vector(patient_id, report_id, day_wise_reports):
    try:
        from lib.dependencies.service_dependencies import (
            get_cgm_vector_service,
            get_patient_profile_service,
        )

        vector_service = get_cgm_vector_service()
        patient_service = get_patient_profile_service()

        patient_profile = await patient_service.fetch_patient_profile(
            patient_id
        )
        if not patient_profile:
            print(f"⚠️ Patient profile not found for {patient_id}")
            return

        await vector_service.upsert_report(
            patient_id,
            report_id,
            day_wise_reports,
            patient_profile.age,
            patient_profile.gender,
        )
        print(f"✅ Successfully generated CGM vector for {patient_id}")

    except Exception as error:
        print(f"❌ Failed to generate CGM vector for {patient_id}: {error}")
