"""Fitness Report Generation Tasks - Optimized."""

from datetime import datetime
from typing import Any, Dict, List

from loguru import logger

from lib.services.reports import FitnessReportType
from lib.utils.date_utils import get_month_start_end, get_months_between_dates
from lib.utils.datetime_utils import normalize_to_date_iso, parse_datetime
from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.workers.tasks.base import TaskResult, task_with_logging
from lib.workers.tasks.fitness.vector_generation import _trigger_vector_generation


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
    from lib.dependencies.service_dependencies import get_fitness_report_service

    service = get_fitness_report_service()
    now = datetime.now()
    current_year, current_month = now.year, now.month

    # Build list of month start dates to check
    month_starts_iso = []
    month_map = {}
    for year, month in months:
        month_start, month_end = get_month_start_end(year, month)
        start_iso = normalize_to_date_iso(month_start)
        month_starts_iso.append(start_iso)
        month_map[start_iso] = (year, month, month_start, month_end)

    # Batch query existing monthly reports with updated_at
    existing_cursor = service.fitness_report_collection.find(
        {
            "patient_id": patient_id,
            "metadata.report_type": FitnessReportType.MONTHLY,
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

    # Determine which months need processing
    to_process = []
    for year, month in months:
        month_start, month_end = get_month_start_end(year, month)
        start_iso = normalize_to_date_iso(month_start)
        existing = existing_map.get(start_iso)

        is_current_month = year == current_year and month == current_month

        if not existing:
            # No report exists - generate it
            to_process.append((year, month, month_start, month_end))
        elif is_current_month:
            # Current month - always regenerate (data is still coming in)
            to_process.append((year, month, month_start, month_end))
        elif existing["updated_at"] is None:
            # updated_at is None - treat as missing, generate it
            to_process.append((year, month, month_start, month_end))
        elif existing["updated_at"] < month_end:
            # Past month - regenerate if updated BEFORE month ended
            # This means report might be missing end-of-month data
            to_process.append((year, month, month_start, month_end))
        # else: updated_at >= month_end means report was created/updated
        # after month closed, so it has all the data - no regeneration needed

    return to_process


@task_with_logging
async def process_fitness_upload(
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

        # Filter months that need processing (including updates)
        # Reverse so the most recent month is processed first
        months_to_process = await _filter_months_needing_reports(
            patient_id, months_between
        )
        months_to_process.reverse()

        if not months_to_process:
            logger.info(f"All fitness reports up to date for {patient_id}")
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

        # Process all months
        results = []
        for year, month, month_start, month_end in months_to_process:
            result = await _generate_monthly_reports(patient_id, month_start, month_end)
            results.append(result)

        successful = sum(1 for r in results if r.get("success"))

        # Trigger vector generation once after all reports are done
        await _trigger_vector_generation(patient_id, start_date, end_date)

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
        logger.error(f"Failed to process fitness upload for {patient_id}: {e}")
        return TaskResult(
            success=False,
            error=str(e),
            data={"patient_id": patient_id},
        )


async def _generate_monthly_reports(
    patient_id: str,
    start_date: datetime,
    end_date: datetime,
) -> Dict:
    """Generate and save monthly fitness reports (monthly, weekly, daily)."""
    from lib.dependencies.service_dependencies import (
        get_fitness_report_service,
        get_fitness_stats_processor,
    )

    try:
        processor = get_fitness_stats_processor()
        service = get_fitness_report_service()

        reports = await processor.generate_report(
            patient_id,
            start_date,
            end_date,
            report_types=[
                FitnessReportType.MONTHLY,
                FitnessReportType.WEEKLY,
                FitnessReportType.DAILY,
            ],
        )

        if not reports:
            return {
                "success": True,
                "start": start_date.isoformat(),
                "reason": "no_data",
            }

        await service.save_reports_bulk(patient_id, reports)

        logger.info(
            f"Generated {len(reports)} fitness reports for {patient_id}: "
            f"{start_date.date()} - {end_date.date()}"
        )

        return {
            "success": True,
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "count": len(reports),
        }

    except Exception as e:
        logger.error(f"Failed to generate fitness reports for {patient_id}: {e}")
        return {
            "success": False,
            "start": start_date.isoformat(),
            "error": str(e),
        }


@task_with_logging
async def force_regenerate_fitness_reports(
    ctx: Dict[str, Any],
    patient_id: str,
    start_date: datetime,
    end_date: datetime,
) -> TaskResult:
    """Force-regenerate all fitness reports in the date range (skips freshness filter)."""
    try:
        months_between = get_months_between_dates(start_date, end_date)

        if not months_between:
            return TaskResult(
                success=True,
                data={"processed": 0, "reason": "no_valid_months"},
            )

        logger.info(
            f"Force-regenerating {len(months_between)} months for {patient_id}"
        )

        results = []
        for year, month in months_between:
            month_start, month_end = get_month_start_end(year, month)
            result = await _generate_monthly_reports(patient_id, month_start, month_end)
            results.append(result)

        successful = sum(1 for r in results if r.get("success"))

        await _trigger_vector_generation(patient_id, start_date, end_date)

        return TaskResult(
            success=True,
            data={
                "total_months": len(months_between),
                "processed": successful,
                "results": results,
            },
        )

    except Exception as e:
        logger.error(
            f"Failed to force-regenerate fitness reports for {patient_id}: {e}"
        )
        return TaskResult(
            success=False,
            error=str(e),
            data={"patient_id": patient_id},
        )


async def _enqueue_fitness_upload(
    patient_id: str, start_date: datetime, end_date: datetime, job_id: str | None = None
) -> str | None:
    """Internal: Enqueue fitness upload processing."""
    if job_id is None:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        job_id = f"fitness:upload:{patient_id}:{timestamp}"

    job = await enqueue_job(
        "process_fitness_upload",
        patient_id,
        start_date,
        end_date,
        _job_id=job_id,
        _queue_name=Queues.REPORTS,
    )

    if job:
        logger.info(f"Enqueued fitness upload processing for {patient_id}")
    else:
        logger.debug(f"Duplicate fitness upload skipped: {job_id}")

    return job.job_id if job else None
