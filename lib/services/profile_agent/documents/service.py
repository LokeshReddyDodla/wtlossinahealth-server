"""Patient-facing service for the medical documents sub-feature.

Wraps the shared `PatientDocumentService` (which already handles S3
upload + text extraction + summary + Mongo insert + Qdrant embedding)
with patient-scoped reads (list / detail / timeline) and the lifecycle
operations specific to onboarding (start, skip, delete).

Uploads themselves go through `PatientDocumentService.upload_multiple_documents`
directly from the router so the request body multipart parsing works
cleanly.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm.attributes import flag_modified

from lib.core.postgres_store import PostgresStore
from lib.models.patient import Patient
from lib.schemas.profile_agent_documents import (
    DocumentDetail,
    DocumentSummary,
    DocumentsSection,
    FileMeta,
    Finding,
    LinkGroup,
    OverviewResponse,
    StartDocumentsResponse,
    SkipDocumentsResponse,
    TimelineEntry,
    TimelineResponse,
)
from lib.services.patient_document_service import PatientDocumentService
from lib.services.patient_documents_overview import PatientDocumentsOverviewService
from lib.services.profile_agent.documents.linker import group_findings
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.s3_utils import generate_presigned_download_url

logger = logging.getLogger(__name__)


class ProfileAgentDocumentsService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        patient_document_service: PatientDocumentService,
        overview_service: PatientDocumentsOverviewService,
    ) -> None:
        self.postgres_store = postgres_store
        self.patient_document_service = patient_document_service
        self.overview_service = overview_service

    # ── Onboarding lifecycle ───────────────────────────────────────────

    async def start(self, patient_id: str) -> StartDocumentsResponse:
        section = await self._read_documents_section(patient_id)
        has_prior = await self._has_any_documents(patient_id)
        greeting = (
            "Welcome back. You can upload more medical documents any time."
            if has_prior
            else "Do you have any prior medical documents — old lab reports, "
            "prescriptions, discharge summaries, or scans? You can upload them "
            "now or skip this step."
        )
        return StartDocumentsResponse(
            greeting=greeting,
            has_prior_uploads=has_prior,
            documents_section=section,
        )

    async def skip(self, patient_id: str) -> SkipDocumentsResponse:
        section = await self._update_documents_section(
            patient_id, is_complete=True, skipped=True
        )
        return SkipDocumentsResponse(documents_section=section)

    # ── Reads ──────────────────────────────────────────────────────────

    async def list_documents(
        self,
        patient_id: str,
        *,
        category: Optional[str] = None,
        order: Optional[str] = "desc",
        limit: Optional[int] = 50,
        offset: int = 0,
    ) -> List[DocumentSummary]:
        cursor = self.patient_document_service.patient_document_collection.find(  # type: ignore[attr-defined]
            self._not_deleted({"patient_id": patient_id, **({"category": category} if category else {})}),
            {"text_raw": 0, "text_repr": 0},
        ).sort("metadata.created_at", -1 if order == "desc" else 1).skip(offset).limit(limit or 50)

        docs = await cursor.to_list(length=limit or 50)
        return [_to_summary(d) for d in docs]

    async def get_document(
        self, patient_id: str, document_id: str
    ) -> DocumentDetail:
        doc = await self._fetch_one(patient_id, document_id, include_text=False)
        if not doc:
            raise_http_exception(404, "Document not found")
        return _to_detail(doc, download_url=_presigned_download(doc))

    async def timeline(self, patient_id: str) -> TimelineResponse:
        cursor = self.patient_document_service.patient_document_collection.find(  # type: ignore[attr-defined]
            self._not_deleted({"patient_id": patient_id}),
            {"text_raw": 0, "text_repr": 0},
        ).sort("metadata.document_date", 1)

        docs = await cursor.to_list(length=None)

        entries: List[TimelineEntry] = []
        flat: List[Tuple[str, Finding, Dict[str, Any]]] = []
        for d in docs:
            doc_id = str(d["_id"])
            findings = [Finding(**f) for f in (d.get("findings") or [])]
            doc_meta = {
                "document_date": (d.get("metadata") or {}).get("document_date"),
            }
            for f in findings:
                flat.append((doc_id, f, doc_meta))
            entries.append(
                TimelineEntry(
                    id=doc_id,
                    file_name=(d.get("file") or {}).get("name", ""),
                    category=d.get("category", ""),
                    summary_text=d.get("summary_text"),
                    document_date=doc_meta["document_date"],
                    parse_status=d.get("parse_status") or "pending",
                    finding_count=len(findings),
                )
            )

        return TimelineResponse(documents=entries, link_groups=group_findings(flat))

    async def overview(self, patient_id: str) -> Optional[OverviewResponse]:
        return await self.overview_service.fetch(patient_id)

    # ── Delete ─────────────────────────────────────────────────────────

    async def delete(self, patient_id: str, document_id: str) -> None:
        deleted = await self.patient_document_service.delete_patient_document(
            patient_id=patient_id,
            document_id=document_id,
        )
        if not deleted:
            raise_http_exception(404, "Document not found")

    # ── Internal helpers ───────────────────────────────────────────────

    @staticmethod
    def _not_deleted(query: Dict[str, Any]) -> Dict[str, Any]:
        return {**query, "deleted_at": {"$in": [None]}}

    async def _fetch_one(
        self, patient_id: str, document_id: str, include_text: bool
    ) -> Optional[Dict[str, Any]]:
        from bson import ObjectId
        from bson.errors import InvalidId

        try:
            oid = ObjectId(document_id)
        except (InvalidId, TypeError):
            return None

        projection = None if include_text else {"text_raw": 0, "text_repr": 0}
        return await self.patient_document_service.patient_document_collection.find_one(  # type: ignore[attr-defined]
            self._not_deleted({"_id": oid, "patient_id": patient_id}),
            projection,
        )

    async def _has_any_documents(self, patient_id: str) -> bool:
        existing = await self.patient_document_service.patient_document_collection.find_one(  # type: ignore[attr-defined]
            self._not_deleted({"patient_id": patient_id}),
            {"_id": 1},
        )
        return existing is not None

    async def _read_documents_section(self, patient_id: str) -> DocumentsSection:
        async with self.postgres_store.get_session() as session:
            patient = await session.get(Patient, patient_id)
            if patient is None:
                raise_http_exception(404, "Patient not found")
            section = (patient.profile_completion or {}).get("documents") or {}
            return DocumentsSection(
                is_complete=bool(section.get("is_complete", False)),
                is_mandatory=bool(section.get("is_mandatory", False)),
                skipped=bool(section.get("skipped", False)),
            )

    async def _update_documents_section(
        self, patient_id: str, *, is_complete: bool, skipped: bool
    ) -> DocumentsSection:
        async with self.postgres_store.get_session() as session:
            patient = await session.get(Patient, patient_id)
            if patient is None:
                raise_http_exception(404, "Patient not found")
            pc = dict(patient.profile_completion or {})
            pc["documents"] = {
                "is_complete": is_complete,
                "is_mandatory": False,
                "skipped": skipped,
            }
            patient.profile_completion = pc
            flag_modified(patient, "profile_completion")
            await session.commit()
            return DocumentsSection(**pc["documents"])


# ── Mongo doc → schema helpers ─────────────────────────────────────────


def _to_summary(d: Dict[str, Any]) -> DocumentSummary:
    return DocumentSummary(
        id=str(d.get("_id")),
        patient_id=str(d.get("patient_id")),
        file=FileMeta(**(d.get("file") or {})),
        category=d.get("category") or "",
        summary_text=d.get("summary_text"),
        document_date=(d.get("metadata") or {}).get("document_date"),
        parse_status=d.get("parse_status") or "pending",
        parse_error=d.get("parse_error"),
        created_at=(d.get("metadata") or {}).get("created_at"),
        uploaded_by=(d.get("metadata") or {}).get("uploaded_by"),
    )


def _to_detail(d: Dict[str, Any], download_url: Optional[str]) -> DocumentDetail:
    base = _to_summary(d).model_dump()
    base["findings"] = [Finding(**f) for f in (d.get("findings") or [])]
    base["download_url"] = download_url
    return DocumentDetail(**base)


def _presigned_download(d: Dict[str, Any]) -> Optional[str]:
    bucket = d.get("storage_bucket")
    key = d.get("storage_key")
    if not bucket or not key:
        return None
    return generate_presigned_download_url(bucket_name=bucket, object_key=key)
