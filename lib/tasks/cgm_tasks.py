from datetime import datetime, timedelta
import traceback
from typing import List, Tuple

from celery import shared_task


@shared_task(queue="cgm_reports", rate_limit="20/m")
def trigger_cgm_report_generation_for_periods(
    patient_id: str, periods: List[Tuple]
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

        for period in reversed(periods):
            # Handle both old format (2-tuple) and new format (4-tuple with status)
            if len(period) == 2:
                start_raw, end_raw = period
                status = "OPEN"
                termination_reason = None
            elif len(period) == 4:
                start_raw, end_raw, status, termination_reason = period
            else:
                print(f"⚠️ Skipping invalid period format: {period}")
                continue

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
                args=[patient_id, start_date, end_date, status, termination_reason],
                task_id=f"{patient_id}_{start_date.isoformat()}_{end_date.isoformat()}",
                queue="cgm_reports",
            )

            print(
                f"✅ Triggered CGM report for {patient_id} "
                f"({start_date.isoformat()} - {end_date.isoformat()}, status={status})"
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
    status: str = "OPEN",
    termination_reason: str = None,
):
    try:
        from lib.dependencies.service_dependencies import (
            get_cgm_report_service,
            get_cgm_stats_processor,
            get_cgm_sync_cache_store,
        )
        from lib.services.reports import CGMReportType

        processor = get_cgm_stats_processor()
        service = get_cgm_report_service()
        cache_store = get_cgm_sync_cache_store()
        last_synced = _parse_datetime(cache_store.get_key(patient_id))

        # Normalize start_date to beginning of day for comparison
        start_date_normalized = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        next_day_start = start_date_normalized + timedelta(days=1)

        # Check if a custom report with the same start_date (same calendar day) already exists
        existing_report = await service.cgm_report_collection.find_one(
            {
                "patient_id": patient_id,
                "report_type": CGMReportType.CUSTOM,
                "start_date": {"$gte": start_date_normalized, "$lt": next_day_start},
            },
            {"_id": 1, "start_date": 1, "end_date": 1, "status": 1, "termination_reason": 1}
        )

        if existing_report:
            existing_status = existing_report.get("status", "OPEN")
            existing_end = existing_report.get("end_date")
            
            # If report is CLOSED, skip (immutable)
            if existing_status == "CLOSED":
                print(
                    f"⏭️ Skipping CGM report generation for {patient_id} "
                    f"({start_date.isoformat()} - {end_date.isoformat()}) "
                    f"since a CLOSED report already exists with start_date {start_date_normalized.isoformat()} "
                    f"(end_date: {existing_end.isoformat() if existing_end else 'N/A'})"
                )
                return
            
            # If report is OPEN and new end_date doesn't extend it, skip
            if existing_end and end_date <= existing_end:
                print(
                    f"⏭️ Skipping CGM report generation for {patient_id} "
                    f"({start_date.isoformat()} - {end_date.isoformat()}) "
                    f"since OPEN report already exists with end_date {existing_end.isoformat()} "
                    f"(new end_date doesn't extend it)"
                )
                return
            
            # If report is OPEN and new end_date extends it, continue to regenerate
            if existing_end and end_date > existing_end:
                print(
                    f"📅 Extending OPEN report for {patient_id} "
                    f"from {existing_end.isoformat()} to {end_date.isoformat()}"
                )

        reports = await processor.generate_report(
            patient_id, start_date, end_date
        )
        if not reports:
            print(
                f"⚠️ No CGM reports generated for {patient_id} ({start_date} - {end_date})"
            )
            return

        report_id = await service.save_reports_bulk(
            patient_id, reports, status=status, termination_reason=termination_reason
        )
        if not report_id:
            print(f"❌ Failed to save CGM reports for {patient_id}")
            return

        # trigger_cgm_vector_upsert_for_patient.delay(patient_id)  # type: ignore

        latest_processed = max(end_date, last_synced or end_date)
        cache_store.set_key(
            patient_id,
            latest_processed.isoformat(),
            expire=None,
        )

        print(
            f"✅ Successfully generated CGM report for {patient_id} from {start_date} to {end_date}."
        )

    except Exception as error:
        print(
            f"❌ Failed to generate CGM report for {patient_id} from {start_date} to {end_date}. Error: {error}"
        )


@shared_task(queue="vector_sync", rate_limit="5/m")
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

    print(f"🔄 Starting CGM vector sync for {len(patients)} patients")

    for patient in patients:
        patient_id = str(patient.patient_id)

        start_date, end_date = _get_sync_dates(
            cache_store, patient_id, patient.created_at
        )

        # Skip if start_date is >= end_date (nothing to sync)
        if start_date >= end_date:
            print(
                f"⏭️ Skipping {patient_id}: start_date ({start_date.isoformat()}) >= end_date ({end_date.isoformat()})"
            )
            continue

        # Use a more stable task_id that doesn't change with every run
        # Use start_date only, so we don't create duplicate tasks for the same date range
        task_id = f"cgm_qdrant_sync_{patient_id}_{start_date.date().isoformat()}"  # type: ignore

        task_manager.trigger_task_once(
            "lib.tasks.cgm_tasks.sync_patient_daily_cgm_reports_to_vector_store",
            args=[
                patient_id,
                patient.age,
                patient.gender,
                start_date,
                end_date,
            ],
            task_id=task_id,
            queue="vector_sync",
        )

    print(f"✅ Finished triggering CGM vector sync tasks for {len(patients)} patients")


@shared_task(queue="vector_sync", rate_limit="20/m")
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

        # Skip if start_date is >= end_date (nothing to sync)
        if start_date >= end_date:
            print(
                f"⏭️ Skipping {patient_id}: start_date ({start_date.isoformat()}) >= end_date ({end_date.isoformat()})"
            )
            return

        # Use a more stable task_id that doesn't change with every run
        # Use start_date only, so we don't create duplicate tasks for the same date range
        task_id = f"cgm_qdrant_sync_{patient_id}_{start_date.date().isoformat()}"  # type: ignore

        task_manager.trigger_task_once(
            "lib.tasks.cgm_tasks.sync_patient_daily_cgm_reports_to_vector_store",
            args=[
                patient_id,
                patient.age,
                patient.gender,
                start_date,
                end_date,
            ],
            task_id=task_id,
            queue="vector_sync",
        )

    except Exception as error:
        print(f"❌ Failed to generate CGM vector for {patient_id}: {error}")


@shared_task(queue="vector_sync", rate_limit="10/m")
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

    last_synced = _parse_datetime(cache_store.get_key(patient_id))

    # Double-check: skip if start_date >= end_date
    if start_date >= end_date:
        print(
            f"⏭️ Skipping sync for {patient_id}: start_date ({start_date.isoformat()}) >= end_date ({end_date.isoformat()})"
        )
        return

    # If we have a last_synced date and end_date is not newer, skip
    if last_synced and end_date <= last_synced:
        print(
            f"⏭️ Skipping sync for {patient_id}: end_date ({end_date.isoformat()}) <= last_synced ({last_synced.isoformat()})"
        )
        return

    reports = await report_service.fetch_day_wise_reports(
        patient_id=patient_id,
        start_date=start_date,
        end_date=end_date,
    )

    if not reports:
        print(f"⚠️ No new daily reports to sync for {patient_id}")
        # Still update cache to prevent re-checking the same date range
        if not last_synced or end_date > last_synced:
            cache_store.set_key(patient_id, end_date.isoformat(), expire=None)
        return

    await vector_service.upsert_report(
        patient_id,
        reports,
        patient_age,
        patient_gender,
    )

    latest_processed = max(end_date, last_synced or end_date)
    cache_store.set_key(patient_id, latest_processed.isoformat(), expire=None)
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
