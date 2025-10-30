from datetime import datetime
from typing import List, Tuple

from celery import shared_task
from sqlalchemy.future import select

from lib.models.patient import Patient


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

        sync_daily_cgm_reports_for_single_patient.delay(patient_id)

        print(
            f"✅ Successfully generated CGM report for {patient_id} from {start_date} to {end_date}."
        )

    except Exception as error:
        print(
            f"❌ Failed to generate CGM report for {patient_id} from {start_date} to {end_date}. Error: {error}"
        )


@shared_task
async def sync_all_daily_cgm_reports():

    from lib.dependencies.service_dependencies import (
        get_cgm_qdrant_sync_cache_store,
        get_libreview_service,
        get_celery_task_manager,
    )

    libreview_service = get_libreview_service()
    cache_store = get_cgm_qdrant_sync_cache_store()
    task_manager = get_celery_task_manager()

    patients = await libreview_service.get_patients_with_libreview()  # type: ignore

    for patient in patients:
        patient_id = patient.patient_id
        last_synced = cache_store.get_key(patient_id)

        start_date = last_synced or patient.created_at
        end_date = datetime.now()

        task_manager.trigger_task_once(
            "lib.tasks.cgm_tasks.sync_daily_cgm_reports_for_patient",
            args=[
                patient_id,
                patient.age,
                patient.gender,
                start_date,
                end_date,
            ],
            task_id=f"cgm_sync_{patient_id}_{start_date.date()}_{end_date.date()}",  # type: ignore
        )


@shared_task
async def sync_daily_cgm_reports_for_single_patient(patient_id: str):
    try:
        from lib.dependencies.service_dependencies import (
            get_celery_task_manager,
            get_patient_profile_service,
            get_cgm_qdrant_sync_cache_store,
        )

        patient_service = get_patient_profile_service()
        cache_store = get_cgm_qdrant_sync_cache_store()
        task_manager = get_celery_task_manager()

        patient = await patient_service.fetch_patient_profile(patient_id)
        if not patient:
            print(f"⚠️ Patient profile not found for {patient_id}")
            return

        last_synced = cache_store.get_key(patient_id)

        start_date = last_synced or patient.created_at
        end_date = datetime.now()

        task_manager.trigger_task_once(
            "lib.tasks.cgm_tasks.sync_daily_cgm_reports_for_patient",
            args=[
                patient_id,
                patient.age,
                patient.gender,
                start_date,
                end_date,
            ],
            task_id=f"cgm_sync_{patient_id}_{start_date.date()}_{end_date.date()}",  # type: ignore
        )

    except Exception as error:
        print(f"❌ Failed to generate CGM vector for {patient_id}: {error}")


@shared_task
async def sync_daily_cgm_reports_for_patient(
    patient_id: str,
    patient_age: int,
    patient_gender: str,
    start_date: datetime,
    end_date: datetime,
):
    from lib.dependencies.service_dependencies import (
        get_cgm_report_service,
        get_cgm_vector_service,
        get_cgm_qdrant_sync_cache_store,
    )

    report_service = get_cgm_report_service()
    vector_service = get_cgm_vector_service()
    cache_store = get_cgm_qdrant_sync_cache_store()

    reports = await report_service.fetch_day_wise_reports(
        patient_id=patient_id,
        start_date=start_date,
        end_date=end_date,
    )

    if not reports:
        print(f"⚠️ No new daily reports to sync for {patient_id}")
        return

    await vector_service.upsert_report(
        patient_id,
        reports,
        patient_age,
        patient_gender,
    )

    cache_store.set_key(patient_id, end_date.isoformat(), expire=None)
    print(f"✅ Synced {len(reports)} daily reports to Qdrant for {patient_id}")
