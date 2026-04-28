"""Enqueue helpers for the medical-documents pipeline.

Both jobs are dedup'd via `_job_id`:

  * `documents:extract:{document_id}` — one extraction per document. Re-enqueueing
    the same id is a no-op (logged "Duplicate job skipped"), which is safe and
    desirable.
  * `documents:overview:rebuild:{patient_id}` — one rebuild in flight per patient.
    If three uploads land back-to-back the first job covers the latest state by
    the time it executes; subsequent enqueues are skipped until it completes.
"""

from __future__ import annotations

import logging
from typing import Optional

from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job

logger = logging.getLogger(__name__)


async def enqueue_extract_findings(document_id: str) -> Optional[str]:
    job_id = f"documents:extract:{document_id}"
    job = await enqueue_job(
        "extract_document_findings",
        document_id,
        _job_id=job_id,
        _queue_name=Queues.REPORTS,
    )
    return job.job_id if job else None


async def enqueue_rebuild_overview(patient_id: str) -> Optional[str]:
    job_id = f"documents:overview:rebuild:{patient_id}"
    job = await enqueue_job(
        "rebuild_patient_documents_overview",
        patient_id,
        _job_id=job_id,
        _queue_name=Queues.REPORTS,
    )
    return job.job_id if job else None
