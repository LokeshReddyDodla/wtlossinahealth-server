from datetime import datetime
import traceback
from typing import List, Tuple

from celery import shared_task


@shared_task(queue="cgm_reports", rate_limit="20/m")
def trigger_cgm_report_generation_for_periods(
    patient_id: str, periods: List[Tuple[datetime, datetime]]
):
    from lib.dependencies.service_dependencies import (
        get_celery_task_manager,
        get_cgm_sync_cache_store,
    )

    try:
        task_manager = get_celery_task_manager()
        cache_store = get_cgm_sync_cache_store()

        last_synced = _parse_datetime(cache_store.get_key(patient_id))
        if last_synced:
            print(
                f"🕒 Last synced for {patient_id}: {last_synced.isoformat()}"
            )

        for start_raw, end_raw in reversed(periods):
            start_date = _parse_datetime(start_raw)
            end_date = _parse_datetime(end_raw)

            if not start_date or not end_date:
                print(f"⚠️ Skipping invalid period: {start_raw} - {end_raw}")
                continue

            # Skip if this period is older or equal to last sync
            if last_synced and end_date <= last_synced:
                print(
                    f"⏭️ Skipping CGM report for {patient_id} "
                    f"({start_date.isoformat()} - {end_date.isoformat()}) "
                    f"since already synced up to {last_synced.isoformat()}."
                )
                continue

            task_manager.trigger_task_once(
                "lib.tasks.cgm_tasks.generate_and_store_cgm_report",
                args=[patient_id, start_date, end_date],
                task_id=f"{patient_id}_{start_date.isoformat()}_{end_date.isoformat()}",
                queue="cgm_reports",
            )

            print(
                f"✅ Triggered CGM report for {patient_id} "
                f"({start_date.isoformat()} - {end_date.isoformat()})"
            )

    except Exception as e:
        traceback_message = traceback.format_exc()
        print("🚀 ~ traceback_message:", traceback_message)
        print(
            f"❌ Failed to generate CGM reports for {patient_id}. Error: {e}"
        )


@shared_task(queue="cgm_reports", rate_limit="30/m")
async def generate_and_store_cgm_report(
    patient_id: str,
    start_date: datetime,
    end_date: datetime,
):
    try:
        from lib.dependencies.service_dependencies import (
            get_cgm_report_service,
            get_cgm_stats_processor,
            get_cgm_sync_cache_store,
        )

        processor = get_cgm_stats_processor()
        service = get_cgm_report_service()
        cache_store = get_cgm_sync_cache_store()

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

        # trigger_cgm_vector_upsert_for_patient.delay(patient_id)  # type: ignore

        cache_store.set_key(patient_id, end_date.isoformat(), expire=None)
        print(
            f"✅ Successfully generated CGM report for {patient_id} from {start_date} to {end_date}."
        )

    except Exception as error:
        print(
            f"❌ Failed to generate CGM report for {patient_id} from {start_date} to {end_date}. Error: {error}"
        )


@shared_task(queue="cgm_reports", rate_limit="5/m")
async def trigger_cgm_vector_upsert_for_all_patients():

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
        patient_id = str(patient.patient_id)

        start_date, end_date = _get_sync_dates(
            cache_store, patient_id, patient.created_at
        )

        task_manager.trigger_task_once(
            "lib.tasks.cgm_tasks.sync_patient_daily_cgm_reports_to_vector_store",
            args=[
                patient_id,
                patient.age,
                patient.gender,
                start_date,
                end_date,
            ],
            task_id=f"cgm_qdrant_sync_{patient_id}_{start_date.date()}_{end_date.date()}",  # type: ignore
            queue="cgm_reports",
        )


@shared_task(queue="cgm_reports", rate_limit="20/m")
async def trigger_cgm_vector_upsert_for_patient(patient_id: str):
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

        start_date, end_date = _get_sync_dates(
            cache_store, patient_id, patient.created_at
        )

        task_manager.trigger_task_once(
            "lib.tasks.cgm_tasks.sync_patient_daily_cgm_reports_to_vector_store",
            args=[
                patient_id,
                patient.age,
                patient.gender,
                start_date,
                end_date,
            ],
            task_id=f"cgm_qdrant_sync_{patient_id}_{start_date.date()}_{end_date.date()}",  # type: ignore
            queue="cgm_reports",
        )

    except Exception as error:
        print(f"❌ Failed to generate CGM vector for {patient_id}: {error}")


@shared_task(queue="cgm_reports", rate_limit="10/m")
async def sync_patient_daily_cgm_reports_to_vector_store(
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


def _parse_datetime(value):
    if not value:
        return None
    try:
        if isinstance(value, datetime):
            return value
        if isinstance(value, bytes):
            value = value.decode()
        if isinstance(value, str):
            return datetime.fromisoformat(value)
    except Exception:
        pass
    return None


def _get_sync_dates(
    cache_store, patient_id: str, patient_created_at: datetime
) -> tuple[datetime, datetime]:
    last_synced = cache_store.get_key(patient_id)

    if last_synced:
        try:
            if isinstance(last_synced, bytes):
                last_synced = datetime.fromisoformat(last_synced.decode())
            elif isinstance(last_synced, str):
                last_synced = datetime.fromisoformat(last_synced)
        except Exception:
            last_synced = None

    start_date = last_synced or patient_created_at
    end_date = datetime.now()

    return start_date, end_date
