"""arq task: rebuild the per-patient documents overview.

Triggered after every findings extraction (and after deletes). Reads all
of a patient's non-deleted documents, recomputes deterministic
link_groups via `linker.group_findings`, asks an LLM for a holistic
narrative, and upserts a single row in the `patient_documents_overview`
collection so both the patient view and the doctor view read the same
up-to-date state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Tuple

from loguru import logger
from openai import AsyncOpenAI

from lib.schemas.profile_agent_documents import Finding
from lib.workers.tasks.base import TaskResult, task_with_logging


@task_with_logging
async def rebuild_patient_documents_overview(
    ctx: Dict[str, Any],
    patient_id: str,
) -> TaskResult:
    from lib.dependencies.service_dependencies import (
        get_patient_documents_collection,
        get_patient_documents_overview_service,
    )
    from lib.services.profile_agent.documents.linker import group_findings
    from lib.services.profile_agent.documents.overview_llm import generate_narrative

    documents_collection = get_patient_documents_collection()
    overview_service = get_patient_documents_overview_service()

    cursor = documents_collection.find(
        {"patient_id": patient_id, "deleted_at": {"$in": [None]}},
        {"text_raw": 0, "text_repr": 0},
    ).sort("metadata.document_date", 1)

    docs = await cursor.to_list(length=None)

    if not docs:
        await overview_service.upsert(
            patient_id=patient_id,
            summary_text="No medical documents on file yet.",
            key_observations=[],
            link_groups=[],
            source_document_ids=[],
            latest_document_date=None,
            document_count=0,
        )
        return TaskResult(success=True, data={"patient_id": patient_id, "documents": 0})

    flat: List[Tuple[str, Finding, Dict[str, Any]]] = []
    doc_summaries: List[Dict[str, Any]] = []
    source_ids: List[str] = []
    latest_date: datetime | None = None

    for d in docs:
        doc_id = str(d["_id"])
        source_ids.append(doc_id)

        meta = d.get("metadata") or {}
        document_date = meta.get("document_date")
        if isinstance(document_date, datetime):
            if latest_date is None or document_date > latest_date:
                latest_date = document_date

        doc_summaries.append(
            {
                "document_date": document_date,
                "category": d.get("category"),
                "summary_text": d.get("summary_text"),
            }
        )

        for raw in d.get("findings") or []:
            try:
                flat.append((doc_id, Finding(**raw), {"document_date": document_date}))
            except Exception as e:
                logger.debug(f"rebuild_overview: dropped invalid finding on {doc_id}: {e}")

    link_groups = group_findings(flat)

    client = AsyncOpenAI()
    narrative = await generate_narrative(
        client=client, documents=doc_summaries, link_groups=link_groups
    )

    await overview_service.upsert(
        patient_id=patient_id,
        summary_text=narrative.summary_text,
        key_observations=narrative.key_observations,
        link_groups=link_groups,
        source_document_ids=source_ids,
        latest_document_date=latest_date,
        document_count=len(docs),
    )

    logger.info(
        f"rebuild_overview: patient {patient_id} → {len(docs)} docs, "
        f"{len(link_groups)} link groups"
    )

    return TaskResult(
        success=True,
        data={
            "patient_id": patient_id,
            "documents": len(docs),
            "link_groups": len(link_groups),
        },
    )
