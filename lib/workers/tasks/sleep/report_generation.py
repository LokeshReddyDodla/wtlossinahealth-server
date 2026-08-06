"""Sleep Report Generation Tasks - Optimized."""

from datetime import datetime
from typing import Any, Dict, List

from loguru import logger

from lib.services.reports import SleepReportType
from lib.utils.date_utils import get_month_start_end, get_months_between_dates
from lib.utils.datetime_utils import normalize_to_date_iso, parse_datetime
from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging


async def _filter_months_needing_reports(
    patient_id: str, months: List[tuple[int, int]]
) -> List[tuple[int, int, datetime, datetime]]:
    """Filter months that need report generation or updates.

    Logic:
    - Current month: Always regenerate (data is still coming in)
    - Past month with no report: Generate it
    - Past month with report:
      - If updated_at < month_end: Regenerate (might be missing end-of-month data)
      - If updated_at >= month_end: No regeneration (report created after month closed)
      - If updated_at is None: Treat as missing, generate it
    """
    from lib.dependencies.service_dependencies import get_sleep_report_service

    service = get_sleep_report_service()
    now = datetime.now()
    current_year, current_month = now.year, now.month

    month_starts_iso = []
    month_map = {}
    for year, month in months:
        month_start, month_end = get_month_start_end(year, month)
        start_iso = normalize_to_date_iso(month_start)
        month_starts_iso.append(start_iso)
        month_map[start_iso] = (year, month, month_start, month_end)

    existing_cursor = service.sleep_report_collection.find(
        {
            "patient_id": patient_id,
            "metadata.report_type": SleepReportType.MONTHLY,
            "metadata.date_range.start": {"$in": month_starts_iso},
        },
        {
            "_id": 1,
            "metadata.date_range.start": 1,
            "metadata.date_range.end": 1,
            "updated_at": 1,
        },
    )
    existing_reports = await existing_cursor.to_list(length=None)

    existing_map = {}
    for report in existing_reports:
        start = report.get("metadata", {}).get("date_range", {}).get("start")
        if start:
            start_normalized = normalize_to_date_iso(start)
            updated_at = report.get("updated_at")
            if isinstance(updated_at, str):
                updated_at = parse_datetime(updated_at)
            elif not isinstance(updated_at, datetime):
                updated_at = None

            existing_map[start_normalized] = {
                "updated_at": updated_at,
            }

    to_process = []
    for year, month in months:
        month_start, month_end = get_month_start_end(year, month)
        start_iso = normalize_to_date_iso(month_start)
        existing = existing_map.get(start_iso)

        is_current_month = year == current_year and month == current_month

        if not existing:
            to_process.append((year, month, month_start, month_end))
        elif is_current_month:
            to_process.append((year, month, month_start, month_end))
        elif existing["updated_at"] is None:
            to_process.append((year, month, month_start, month_end))
        elif existing["updated_at"] < month_end:
            to_process.append((year, month, month_start, month_end))

    return to_process


@task_with_logging
async def process_sleep_upload(
    ctx: Dict[str, Any],
    patient_id: str,
    start_date: datetime,
    end_date: datetime,
) -> TaskResult:
    """Main task: batch check which months need reports, then process them."""
    try:
        months_between = get_months_between_dates(start_date, end_date)

        if not months_between:
            return TaskResult(
                success=True,
                data={"processed": 0, "reason": "no_valid_months"},
            )

        months_to_process = await _filter_months_needing_reports(
            patient_id, months_between
        )

        if not months_to_process:
            logger.info(f"All sleep reports up to date for {patient_id}")
            return TaskResult(
                success=True,
                data={
                    "total_months": len(months_between),
                    "processed": 0,
                    "reason": "all_up_to_date",
                },
            )

        logger.info(
            f"Processing {len(months_to_process)}/{len(months_between)} months for {patient_id}"
        )

        results = []
        for year, month, month_start, month_end in months_to_process:
            result = await _generate_monthly_reports(patient_id, month_start, month_end)
            results.append(result)

        successful = sum(1 for r in results if r.get("success"))

        return TaskResult(
            success=True,
            data={
                "total_months": len(months_between),
                "needed_processing": len(months_to_process),
                "processed": successful,
                "results": results,
            },
        )

    except Exception as e:
        logger.error(f"Failed to process sleep upload for {patient_id}: {e}")
        return TaskResult(
            success=False,
            error=str(e),
            data={"patient_id": patient_id},
        )


async def _fetch_sleep_checkins(
    patient_id: str, start_date: datetime, end_date: datetime
) -> List[dict]:
    """Manual sleep check-ins for the range, so no-wearable nights still count."""
    from sqlalchemy import select

    from lib.dependencies.database import get_async_postgres_session
    from lib.models.sleep_checkin import SleepCheckin

    try:
        async with get_async_postgres_session() as session:
            result = await session.execute(
                select(SleepCheckin).where(
                    SleepCheckin.patient_id == patient_id,
                    SleepCheckin.checkin_date >= start_date.date(),
                    SleepCheckin.checkin_date <= end_date.date(),
                )
            )
            return [
                {
                    "checkin_date": r.checkin_date,
                    "hours_slept": r.hours_slept,
                    "quality": r.quality,
                    "bed_time": r.bed_time,
                    "wake_time": r.wake_time,
                }
                for r in result.scalars().all()
            ]
    except Exception as e:
        logger.error(f"Failed to fetch sleep check-ins for {patient_id}: {e}")
        return []


async def _generate_monthly_reports(
    patient_id: str,
    start_date: datetime,
    end_date: datetime,
) -> Dict:
    """Generate and save monthly sleep reports (monthly, weekly, daily)."""
    from lib.dependencies.service_dependencies import (
        get_sleep_report_service,
        get_sleep_stats_processor,
    )

    try:
        processor = get_sleep_stats_processor()
        service = get_sleep_report_service()

        checkins = await _fetch_sleep_checkins(patient_id, start_date, end_date)

        reports = processor.generate_report(
            patient_id,
            start_date,
            end_date,
            report_types=[
                SleepReportType.MONTHLY,
                SleepReportType.WEEKLY,
                SleepReportType.DAILY,
            ],
            sleep_checkins=checkins,
        )

        if not reports:
            return {
                "success": True,
                "start": start_date.isoformat(),
                "reason": "no_data",
            }

        await service.save_reports_bulk(patient_id, reports)

        logger.info(
            f"Generated {len(reports)} sleep reports for {patient_id}: "
            f"{start_date.date()} - {end_date.date()}"
        )

        return {
            "success": True,
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "count": len(reports),
        }

    except Exception as e:
        logger.error(f"Failed to generate sleep reports for {patient_id}: {e}")
        return {
            "success": False,
            "start": start_date.isoformat(),
            "error": str(e),
        }


async def _enqueue_sleep_upload(
    patient_id: str, start_date: datetime, end_date: datetime
) -> str | None:
    """Internal: Enqueue sleep upload processing."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    job_id = f"sleep:upload:{patient_id}:{timestamp}"

    job = await enqueue_job(
        "process_sleep_upload",
        patient_id,
        start_date,
        end_date,
        _job_id=job_id,
        _queue_name=Queues.REPORTS,
    )

    if job:
        logger.info(f"Enqueued sleep upload processing for {patient_id}")
    else:
        logger.debug(f"Duplicate sleep upload skipped: {job_id}")

    return job.job_id if job else None
