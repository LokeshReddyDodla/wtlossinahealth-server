"""CGM Report Generation Tasks."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from lib.utils.datetime_utils import normalize_to_date_iso, parse_datetime
from lib.workers.tasks.base import TaskResult, task_with_logging
from lib.workers.tasks.cgm.vector_generation import _trigger_vector_generation


async def filter_periods_needing_work(
    patient_id: str, periods: List[Dict]
) -> List[Dict]:
    """Batch check MongoDB - returns only periods that need processing."""
    from lib.dependencies.service_dependencies import get_cgm_report_service

    service = get_cgm_report_service()

    start_dates_iso = [normalize_to_date_iso(p["start"]) for p in periods]

    existing_cursor = service.cgm_report_collection.find(
        {
            "patient_id": patient_id,
            "metadata.report_type": "custom",
            "metadata.date_range.start": {"$in": start_dates_iso},
        },
        {
            "_id": 1,
            "metadata.date_range.start": 1,
            "metadata.date_range.end": 1,
            "sensor_status": 1,
        },
    )
    existing_reports = await existing_cursor.to_list(length=None)

    existing_map = {}
    for report in existing_reports:
        start = report.get("metadata", {}).get("date_range", {}).get("start")
        if start:
            start_normalized = normalize_to_date_iso(start)
            existing_map[start_normalized] = {
                "end": report.get("metadata", {}).get("date_range", {}).get("end"),
                "sensor_status": report.get("sensor_status", "OPEN"),
            }

    to_process = []
    for period in periods:
        start_iso = normalize_to_date_iso(period["start"])
        end_iso = (
            period["end"].isoformat()
            if isinstance(period["end"], datetime)
            else period["end"]
        )

        existing = existing_map.get(start_iso)

        if not existing:
            to_process.append(period)
            continue

        if existing["sensor_status"] == "CLOSED":
            continue

        # Reprocess if: end date extended OR status changed to CLOSED
        if existing["end"] and end_iso > existing["end"]:
            to_process.append(period)
        elif period["sensor_status"] == "CLOSED":
            to_process.append(period)

    return to_process


@task_with_logging
async def process_cgm_upload(
    ctx: Dict[str, Any],
    patient_id: str,
    periods: List[Dict],
) -> TaskResult:
    """Main task: batch check which periods need work, then process them."""
    periods_normalized = []
    for period in periods:
        start_dt = parse_datetime(period["start"])
        end_dt = parse_datetime(period["end"])

        if not start_dt or not end_dt:
            continue

        periods_normalized.append(
            {
                "start": start_dt,
                "end": end_dt,
                "sensor_status": period["sensor_status"],
                "termination_reason": period.get("termination_reason"),
            }
        )

    if not periods_normalized:
        return TaskResult(
            success=True, data={"processed": 0, "reason": "no_valid_periods"}
        )

    to_process = await filter_periods_needing_work(patient_id, periods_normalized)

    if not to_process:
        logger.info(f"No periods need processing for {patient_id}")

        # TODO: Rethink this. We should only trigger vector generation if we have new reports.
        await _trigger_vector_generation(
            patient_id,
            min(p["start"] for p in periods_normalized),
            max(p["end"] for p in periods_normalized),
        )

        return TaskResult(
            success=True,
            data={
                "total_periods": len(periods_normalized),
                "processed": 0,
                "reason": "all_up_to_date",
            },
        )

    logger.info(
        f"Processing {len(to_process)}/{len(periods_normalized)} periods for {patient_id}"
    )

    results = []
    for period in to_process:
        result = await _generate_single_report(
            patient_id,
            period["start"],
            period["end"],
            period["sensor_status"],
            period.get("termination_reason"),
        )
        results.append(result)

    successful = sum(1 for r in results if r.get("success"))

    # Trigger vector generation once after all reports are done
    start_date = min(p["start"] for p in periods_normalized)
    end_date = max(p["end"] for p in periods_normalized)
    await _trigger_vector_generation(patient_id, start_date, end_date)

    return TaskResult(
        success=True,
        data={
            "total_periods": len(periods_normalized),
            "needed_processing": len(to_process),
            "processed": successful,
            "results": results,
        },
    )


async def _generate_single_report(
    patient_id: str,
    start_date: datetime,
    end_date: datetime,
    sensor_status: str,
    termination_reason: Optional[str],
) -> Dict:
    """Generate and save a single CGM report."""
    from lib.dependencies.service_dependencies import (
        get_cgm_report_service,
        get_cgm_stats_processor,
    )

    try:
        processor = get_cgm_stats_processor()
        service = get_cgm_report_service()

        reports = await processor.generate_report(patient_id, start_date, end_date)

        if not reports:
            return {
                "success": True,
                "start": start_date.isoformat(),
                "reason": "no_data",
            }

        report_id = await service.save_reports_bulk(
            patient_id,
            reports,
            sensor_status=sensor_status,
            termination_reason=termination_reason or "",
        )

        logger.info(
            f"Generated {len(reports)} reports for {patient_id}: {start_date.date()} - {end_date.date()}"
        )

        return {
            "success": True,
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "report_id": report_id,
            "count": len(reports),
        }

    except Exception as e:
        logger.error(f"Failed to generate report for {patient_id}: {e}")
        return {"success": False, "start": start_date.isoformat(), "error": str(e)}


async def _enqueue_cgm_reports(patient_id: str, periods: List[Dict]) -> Optional[str]:
    """Internal: Enqueue CGM report processing."""
    if not periods:
        return None

    job_id = f"cgm:upload:{patient_id}:{datetime.now().strftime('%Y%m%d%H%M')}"

    job = await enqueue_job(
        "process_cgm_upload",
        patient_id,
        periods,
        _job_id=job_id,
        _queue_name=Queues.REPORTS,
    )

    if job:
        logger.info(
            f"Enqueued CGM processing for {patient_id} ({len(periods)} periods)"
        )

    return job.job_id if job else None
