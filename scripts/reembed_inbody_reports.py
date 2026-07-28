"""Backfill Qdrant vectors for existing InBody reports.

Reports uploaded before the InBody vector service existed have no point in
Qdrant, so the health-query agent cannot retrieve them. New uploads embed
automatically after extraction; this script walks every usable report
(status extracted/needs_review) and enqueues a vector job for each. The arq
worker handles the actual embedding asynchronously.

Job ids are timestamped per run, and point ids derive from report_id, so
re-running is safe — each report's point is overwritten in place.

Usage:
    python scripts/reembed_inbody_reports.py            # apply
    python scripts/reembed_inbody_reports.py --dry-run  # report only
    python scripts/reembed_inbody_reports.py --limit 50 # subset

Inside Docker:
    docker compose exec api python scripts/reembed_inbody_reports.py
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.future import select  # noqa: E402

from lib.core.postgres_store import PostgresStore  # noqa: E402
from lib.models.patient_inbody_report import PatientInbodyReport  # noqa: E402
from lib.workers.tasks.inbody.vector_generation import (  # noqa: E402
    USABLE_REPORT_STATUSES,
    _enqueue_inbody_vector,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger("reembed_inbody_reports")


async def run(dry_run: bool, limit: int | None) -> None:
    store = PostgresStore()
    try:
        async with store.get_session() as session:
            stmt = (
                select(
                    PatientInbodyReport.patient_id,
                    PatientInbodyReport.report_id,
                )
                .where(
                    PatientInbodyReport.status.in_(USABLE_REPORT_STATUSES)
                )
                .order_by(PatientInbodyReport.created_at)
            )
            if limit:
                stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            rows = result.all()

        total = len(rows)
        logger.info(f"─── Walking {total} usable InBody reports ───")

        enqueued = 0
        skipped = 0
        errored = 0

        for i, (patient_id, report_id) in enumerate(rows, start=1):
            try:
                if dry_run:
                    skipped += 1
                else:
                    job_id = await _enqueue_inbody_vector(
                        str(patient_id), str(report_id)
                    )
                    if job_id:
                        enqueued += 1
                    else:
                        skipped += 1
            except Exception as e:
                errored += 1
                logger.warning(f"  ⚠️  {report_id}: {e}")

            if i % 100 == 0:
                logger.info(
                    f"  progress: {i}/{total} "
                    f"(enqueued={enqueued}, skipped={skipped}, errored={errored})"
                )

        logger.info("─── Done ───")
        logger.info(f"  total reports:      {total}")
        logger.info(f"  enqueued:           {enqueued}")
        logger.info(f"  skipped/deduped:    {skipped}")
        logger.info(f"  errored:            {errored}")
        if dry_run:
            logger.info("Dry-run mode — no jobs were enqueued.")
        else:
            logger.info(
                "Embedding runs in the background. "
                "Check arq worker logs for progress."
            )
    finally:
        await store.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Walk reports without enqueueing any jobs.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N reports (useful for a smoke test).",
    )
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run, limit=args.limit))


if __name__ == "__main__":
    main()
