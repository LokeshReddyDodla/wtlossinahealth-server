"""arq task: structured findings extraction for one uploaded document.

Runs after the existing inline upload pipeline (S3 + text + summary +
embedding). Reads the persisted `text_raw` / `summary_text` from Mongo,
asks gpt-4o-mini for structured findings, patches them onto the same
Mongo document, and enqueues the cross-document overview rebuild.
"""

from __future__ import annotations

from typing import Any, Dict

from bson import ObjectId
from loguru import logger
from openai import AsyncOpenAI

from lib.workers.tasks.base import TaskResult, task_with_logging
from lib.workers.tasks.medical_documents.enqueue import enqueue_rebuild_overview


@task_with_logging
async def extract_document_findings(
    ctx: Dict[str, Any],
    document_id: str,
) -> TaskResult:
    from lib.dependencies.service_dependencies import (
        get_patient_documents_collection,
    )
    from lib.services.profile_agent.documents.findings_llm import extract_findings

    collection = get_patient_documents_collection()

    try:
        oid = ObjectId(document_id)
    except Exception as e:
        return TaskResult(
            success=False, error=f"invalid document_id: {e}", data={"document_id": document_id}
        )

    doc = await collection.find_one({"_id": oid})
    if not doc:
        logger.warning(f"extract_document_findings: doc {document_id} not found")
        return TaskResult(success=False, error="not_found", data={"document_id": document_id})

    if doc.get("deleted_at"):
        return TaskResult(success=True, data={"document_id": document_id, "skipped": "deleted"})

    text_raw = doc.get("text_raw") or ""
    summary_text = doc.get("summary_text") or ""

    if not text_raw.strip():
        await collection.update_one(
            {"_id": oid},
            {"$set": {"parse_status": "failed", "parse_error": "empty_text_raw"}},
        )
        return TaskResult(success=False, error="empty_text_raw", data={"document_id": document_id})

    await collection.update_one(
        {"_id": oid},
        {"$set": {"parse_status": "extracting", "parse_error": None}},
    )

    client = AsyncOpenAI()
    try:
        findings = await extract_findings(
            client=client, text_raw=text_raw, summary_text=summary_text
        )
    except Exception as e:
        await collection.update_one(
            {"_id": oid},
            {"$set": {"parse_status": "failed", "parse_error": str(e)[:500]}},
        )
        return TaskResult(success=False, error=str(e), data={"document_id": document_id})

    findings_payload = [f.model_dump(mode="json") for f in findings]

    await collection.update_one(
        {"_id": oid},
        {
            "$set": {
                "findings": findings_payload,
                "parse_status": "parsed",
                "parse_error": None,
            }
        },
    )

    patient_id = str(doc.get("patient_id"))
    await enqueue_rebuild_overview(patient_id)

    logger.info(
        f"extract_document_findings: {document_id} → {len(findings_payload)} findings; "
        f"queued overview rebuild for {patient_id}"
    )

    return TaskResult(
        success=True,
        data={
            "document_id": document_id,
            "patient_id": patient_id,
            "finding_count": len(findings_payload),
        },
    )
