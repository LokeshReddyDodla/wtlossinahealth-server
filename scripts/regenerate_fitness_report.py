"""One-off: regenerate a patient's fitness reports for the month containing a
date, inline (no worker/queue), using the current processor code — so a stale
cached report gets rebuilt with the corrected manual-workout merge.

Usage:  python scripts/regenerate_fitness_report.py <patient_id> <YYYY-MM-DD>
"""

import asyncio
import sys
from datetime import datetime

from lib.dependencies.service_dependencies import (
    get_fitness_report_service,
    get_fitness_stats_processor,
)
from lib.services.reports import FitnessReportType
from lib.utils.date_utils import get_month_start_end


async def main(patient_id: str, date_str: str) -> None:
    d = datetime.fromisoformat(date_str)
    start, end = get_month_start_end(d.year, d.month)

    processor = get_fitness_stats_processor()
    service = get_fitness_report_service()

    reports = await processor.generate_report(
        patient_id,
        start,
        end,
        report_types=[
            FitnessReportType.MONTHLY,
            FitnessReportType.WEEKLY,
            FitnessReportType.DAILY,
        ],
    )
    await service.save_reports_bulk(patient_id, reports)

    daily = [r for r in reports if r.report_type == FitnessReportType.DAILY]
    print(f"Regenerated {len(reports)} reports ({len(daily)} daily) for {patient_id}")
    for r in daily:
        wk = r.workouts or []
        if wk:
            print(f"  {r.metadata.date_range.start[:10]}: "
                  + ", ".join(f"{w.type} {w.total_duration:g}m/{w.total_energy:g}kcal" for w in wk))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: python scripts/regenerate_fitness_report.py <patient_id> <YYYY-MM-DD>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
