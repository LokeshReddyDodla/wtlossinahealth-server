from datetime import datetime

from celery import shared_task


from lib.utils.date_utils import get_month_start_end, get_months_between_dates
from lib.services.reports import FitnessReportType


@shared_task(queue="default", rate_limit="20/m")
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


@shared_task(queue="default", rate_limit="20/m")
async def generate_and_store_fitness_report_for_month(
    patient_id: str, start_date: datetime, end_date: datetime
):
    try:

        from lib.dependencies.service_dependencies import (
            get_fitness_report_service,
            get_fitness_stats_processor,
            get_celery_task_manager,
        )

        processor = get_fitness_stats_processor()
        service = get_fitness_report_service()
        task_manager = get_celery_task_manager()

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

        task_manager.trigger_task_once(
            "lib.tasks.fitness_tasks.trigger_fitness_vector_upsert_for_patient",
            args=[
                patient_id,
            ],
            task_id=f"fitness_qdrant_sync_{patient_id}_{start_date.date()}_{end_date.date()}",  # type: ignore
            queue="vector_sync",
        )

        print(
            f"✅ Monthly fitness report saved for {patient_id} "
            f"({start_date.isoformat()} – {end_date.isoformat()})"
        )
    except Exception as e:
        print(
            f"❌ Failed monthly fitness report for {patient_id} "
            f"({start_date.isoformat()} – {end_date.isoformat()}). Error: {e}"
        )


@shared_task(queue="default", rate_limit="30/m")
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
            get_celery_task_manager,
        )

        processor = get_fitness_stats_processor()
        service = get_fitness_report_service()
        task_manager = get_celery_task_manager()

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

        task_manager.trigger_task_once(
            "lib.tasks.fitness_tasks.trigger_fitness_vector_upsert_for_patient",
            args=[
                patient_id,
            ],
            task_id=f"fitness_qdrant_sync_{patient_id}_{start_date.date()}_{end_date.date()}",  # type: ignore
            queue="vector_sync",
        )

        print(
            f"✅ Generated {report_type} fitness report for {patient_id} "
            f"({start_date.isoformat()} – {end_date.isoformat()})"
        )
    except Exception as e:
        print(
            f"❌ Failed {report_type} fitness report for {patient_id} "
            f"({start_date.isoformat()} – {end_date.isoformat()}). Error: {e}"
        )


@shared_task(queue="vector_sync", rate_limit="20/m")
async def trigger_fitness_vector_upsert_for_patient(patient_id: str):
    try:
        from lib.dependencies.service_dependencies import (
            get_celery_task_manager,
            get_patient_profile_service,
            get_fitness_qdrant_sync_cache_store,
        )

        patient_service = get_patient_profile_service()
        cache_store = get_fitness_qdrant_sync_cache_store()
        task_manager = get_celery_task_manager()

        patient = await patient_service.fetch_patient_profile(patient_id)
        if not patient:
            print(f"⚠️ Patient profile not found for {patient_id}")
            return

        start_date, end_date = _get_sync_dates(
            cache_store, patient_id, patient.created_at
        )

        task_manager.trigger_task_once(
            "lib.tasks.fitness_tasks.sync_patient_daily_fitness_reports_to_vector_store",
            args=[
                patient_id,
                patient.age,
                patient.gender,
                start_date,
                end_date,
            ],
            task_id=f"fitness_qdrant_sync_{patient_id}_{start_date.date()}_{end_date.date()}",  # type: ignore
            queue="vector_sync",
        )

    except Exception as error:
        print(
            f"❌ Failed to generate Fitness vector for {patient_id}: {error}"
        )


@shared_task(queue="vector_sync", rate_limit="10/m")
async def sync_patient_daily_fitness_reports_to_vector_store(
    patient_id: str,
    patient_age: int,
    patient_gender: str,
    start_date: datetime,
    end_date: datetime,
):
    from lib.dependencies.service_dependencies import (
        get_fitness_report_service,
        get_fitness_vector_service,
        get_fitness_qdrant_sync_cache_store,
    )

    report_service = get_fitness_report_service()
    vector_service = get_fitness_vector_service()
    cache_store = get_fitness_qdrant_sync_cache_store()

    last_synced = _parse_datetime(cache_store.get_key(patient_id))

    reports = await report_service.fetch_daily_reports_in_range(
        patient_id=patient_id,
        start_date=start_date,
        end_date=end_date,
        include_id=True,
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

    latest_processed = max(end_date, last_synced or end_date)
    cache_store.set_key(patient_id, latest_processed.isoformat(), expire=None)
    print(f"✅ Synced {len(reports)} daily reports to Qdrant for {patient_id}")


@shared_task(queue="vector_sync", rate_limit="30/m")
def trigger_fitness_batch_sync(patient_ids: list[str]):
    from lib.tasks.fitness_tasks import (
        trigger_fitness_vector_upsert_for_patient,
    )

    for pid in patient_ids:
        trigger_fitness_vector_upsert_for_patient.delay(pid)  # type: ignore


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
