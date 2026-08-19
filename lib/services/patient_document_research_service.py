from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from bson import ObjectId
from fastapi import HTTPException

from sqlalchemy import asc, desc, inspect, select

from lib.schemas.patient_document_research import (
    PatientDocumentResearchDocument,
    PatientDocumentResearchSelectionItem,
    PatientDocumentResearchSelectionResponse,
    PatientDocumentResearchSource,
)
from lib.services.patient_document_service import PatientDocumentService
from lib.services.medication_service import MedicationService
from lib.services.token_usage_service import TokenUsageService
from lib.utils.http_exceptions import raise_http_exception
from lib.models.patient_prescription import PatientPrescription as PatientPrescriptionModel


class PatientDocumentResearchService:
    MAX_DOCUMENTS = 10
    BATCH_SIZE = 200
    PREVIEW_LENGTH = 280
    MAX_SUMMARY_LENGTH = 4000

    def __init__(
        self,
        patient_document_collection: Any,
        patient_document_summary_interactions_collection: Any,
        patient_document_service: PatientDocumentService,
        medication_service: MedicationService,
        token_usage_service: TokenUsageService,
    ):
        self.patient_document_collection = patient_document_collection
        self.interactions_collection = (
            patient_document_summary_interactions_collection
        )
        self.patient_document_service = patient_document_service
        self.medication_service = medication_service
        self.token_usage_service = token_usage_service

    # -------------------------------------------------------------------------
    # Public API Methods
    # -------------------------------------------------------------------------

    async def fetch_research_selection_options(
        self,
        patient_id: str,
        document_type: Optional[str] = None,
        uploaded_by_type: Optional[str] = None,
        order: Optional[str] = "asc",
    ) -> PatientDocumentResearchSelectionResponse:
        """Fetch all available research sources for selection UI."""
        documents = await self._fetch_all_documents(
            patient_id, document_type, uploaded_by_type, order
        )
        prescriptions = await self._fetch_prescriptions_safe(
            patient_id=patient_id, order=order
        )

        items = [self._map_document_to_selection(d) for d in documents]
        items += [self._map_prescription_to_selection(p) for p in prescriptions]

        return PatientDocumentResearchSelectionResponse(items=items)



    # -------------------------------------------------------------------------
    # Selection Item Mappers
    # -------------------------------------------------------------------------

    def _map_document_to_selection(
        self, doc: dict
    ) -> PatientDocumentResearchSelectionItem:
        metadata = doc.get("metadata") or {}
        uploaded_by = metadata.get("uploaded_by") or {}
        file_info = doc.get("file") or {}

        return PatientDocumentResearchSelectionItem(
            source_type="patient_document",
            source_id=str(doc.get("id") or doc.get("_id")),
            title=file_info.get("name"),
            category=doc.get("category"),
            document_date=metadata.get("document_date"),
            summary_preview=None,
            metadata={
                "file_url": file_info.get("url"),
                "mime_type": file_info.get("type"),
                "uploaded_at": file_info.get("uploaded_at"),
                "uploaded_by_type": uploaded_by.get("type"),
            },
        )

    def _map_prescription_to_selection(
        self, prescription: Any
    ) -> PatientDocumentResearchSelectionItem:
        summary = self._build_prescription_summary(prescription)
        date = getattr(prescription, "prescription_date", None)

        return PatientDocumentResearchSelectionItem(
            source_type="prescription",
            source_id=str(prescription.prescription_id),
            title=f"Prescription {date}" if date else "Prescription",
            category="prescription",
            document_date=self._to_datetime(date),
            summary_preview=self._truncate(summary, self.PREVIEW_LENGTH),
            metadata={
                "file_url": getattr(prescription, "prescription_file_url", None),
                "doctor_name": getattr(prescription, "doctor_name", None),
                "general_advice": getattr(prescription, "general_advice", None),
                "follow_up_required": getattr(prescription, "follow_up_required", None),
                "follow_up_in_days": getattr(prescription, "follow_up_in_days", None),
            },
        )

    # -------------------------------------------------------------------------
    # Document Mappers (for AI context)
    # -------------------------------------------------------------------------

    def _map_document_to_research(
        self, doc: dict
    ) -> PatientDocumentResearchDocument:
        metadata = doc.get("metadata") or {}
        uploaded_by = metadata.get("uploaded_by") or {}
        file_info = doc.get("file") or {}
        summary = (doc.get("summary_text") or doc.get("text_raw") or "").strip()

        return PatientDocumentResearchDocument(
            source_type="patient_document",
            document_id=str(doc.get("_id")),
            file_name=file_info.get("name"),
            file_url=file_info.get("url"),
            mime_type=file_info.get("type"),
            category=doc.get("category"),
            document_date=metadata.get("document_date"),
            uploaded_at=file_info.get("uploaded_at"),
            uploaded_by_type=uploaded_by.get("type"),
            summary_preview=self._truncate(summary, self.PREVIEW_LENGTH),
            summary_text=self._truncate(summary, self.MAX_SUMMARY_LENGTH),
        )

    def _map_prescription_to_research(
        self, prescription: Any
    ) -> PatientDocumentResearchDocument:
        summary = self._build_prescription_summary(prescription)
        date = getattr(prescription, "prescription_date", None)

        return PatientDocumentResearchDocument(
            source_type="prescription",
            document_id=str(prescription.prescription_id),
            file_name=f"Prescription {date}" if date else "Prescription",
            file_url=getattr(prescription, "prescription_file_url", None),
            mime_type=None,
            category="prescription",
            document_date=self._to_datetime(date),
            uploaded_at=getattr(prescription, "created_at", None),
            uploaded_by_type=None,
            summary_preview=self._truncate(summary, self.PREVIEW_LENGTH) or None,
            summary_text=self._truncate(summary, self.MAX_SUMMARY_LENGTH),
        )

    # -------------------------------------------------------------------------
    # Data Fetching
    # -------------------------------------------------------------------------

    async def _fetch_all_documents(
        self,
        patient_id: str,
        document_type: Optional[str],
        uploaded_by_type: Optional[str],
        order: Optional[str],
    ) -> List[dict]:
        documents, offset = [], 0
        while True:
            batch = await self.patient_document_service.fetch_patient_documents(
                patient_id=patient_id,
                document_type=document_type,
                uploaded_by_type=uploaded_by_type,
                order=order,
                limit=self.BATCH_SIZE,
                offset=offset,
            )
            documents.extend(batch)
            if len(batch) < self.BATCH_SIZE:
                break
            offset += self.BATCH_SIZE
        return documents

    async def _fetch_prescriptions_safe(
        self,
        patient_id: str,
        order: Optional[str] = "asc",
    ) -> List[Any]:
        return await self.medication_service.get_patient_prescriptions(
            patient_id=patient_id,
        )

    async def _fetch_source_documents(
        self, patient_id: str, sources: List[PatientDocumentResearchSource]
    ) -> List[PatientDocumentResearchDocument]:
        doc_sources = [s for s in sources if s.source_type == "patient_document"]
        rx_sources = [s for s in sources if s.source_type == "prescription"]

        doc_map: Dict[str, PatientDocumentResearchDocument] = {}
        rx_map: Dict[str, PatientDocumentResearchDocument] = {}

        # Fetch patient documents
        if doc_sources:
            doc_ids = [s.source_id for s in doc_sources]
            self._validate_object_ids(doc_ids)
            docs = await self._fetch_documents_by_ids(patient_id, doc_ids)
            doc_map = {
                str(d["_id"]): self._map_document_to_research(d) for d in docs
            }

        # Fetch prescriptions
        if rx_sources:
            prescriptions = await self._fetch_prescriptions_safe(
                patient_id=patient_id
            )
            rx_map = {
                str(p.prescription_id): self._map_prescription_to_research(p)
                for p in prescriptions
            }
            missing = [s.source_id for s in rx_sources if s.source_id not in rx_map]
            if missing:
                raise_http_exception(404, "Prescriptions not found", {"ids": missing})

        # Build ordered result preserving source order
        result = []
        for source in sources:
            if source.source_type == "patient_document":
                doc = doc_map.get(source.source_id)
            elif source.source_type == "prescription":
                doc = rx_map.get(source.source_id)
            else:
                doc = None
            if doc:
                result.append(doc)

        return result

    async def _fetch_documents_by_ids(
        self, patient_id: str, doc_ids: List[str]
    ) -> List[dict]:
        object_ids = [ObjectId(d) for d in doc_ids]
        cursor = self.patient_document_collection.find(
            {"patient_id": patient_id, "_id": {"$in": object_ids}}
        )
        docs = await cursor.to_list(length=len(object_ids))

        docs_by_id = {str(d["_id"]): d for d in docs}
        missing = [d for d in doc_ids if d not in docs_by_id]
        if missing:
            raise_http_exception(404, "Documents not found", {"ids": missing})

        return [docs_by_id[d] for d in doc_ids]

    # -------------------------------------------------------------------------
    # AI Integration
    # -------------------------------------------------------------------------


    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _normalize_sources(self, request: Any) -> List[PatientDocumentResearchSource]:
        sources: List[PatientDocumentResearchSource] = []
        if request.sources:
            sources.extend(request.sources)
        if request.document_ids:
            sources.extend([
                PatientDocumentResearchSource(
                    source_type="patient_document", source_id=d
                )
                for d in request.document_ids
            ])

        if not sources:
            raise_http_exception(400, "At least one document must be selected")

        # Deduplicate
        seen, unique = set(), []
        for s in sources:
            key = (s.source_type, s.source_id)
            if key not in seen:
                seen.add(key)
                unique.append(s)

        if len(unique) > self.MAX_DOCUMENTS:
            raise_http_exception(
                400, f"Maximum {self.MAX_DOCUMENTS} documents allowed"
            )

        return unique

    def _validate_object_ids(self, ids: List[str]):
        for doc_id in ids:
            if not ObjectId.is_valid(doc_id):
                raise_http_exception(400, f"Invalid document ID: {doc_id}")

    def _build_prescription_summary(self, prescription: Any) -> str:
        parts = []

        if summary := getattr(prescription, "overall_summary", None):
            parts.append(summary)
        if advice := getattr(prescription, "general_advice", None):
            parts.append(f"General advice: {advice}")

        follow_up = getattr(prescription, "follow_up_required", None)
        days = getattr(prescription, "follow_up_in_days", None)
        if follow_up is True:
            parts.append(f"Follow-up required{f' in {days} days' if days else ''}.")
        elif follow_up is False:
            parts.append("Follow-up not required.")

        medicines = []
        try:
            state = inspect(prescription)
            if "medicines" not in state.unloaded:
                medicines = prescription.medicines or []
        except Exception:
            medicines = []

        if medicines:
            lines = []
            for m in medicines:
                name = (
                    getattr(m, "brand_name", None)
                    or getattr(m, "generic_name", None)
                    or "Medication"
                )
                details = [
                    d
                    for d in [
                        getattr(m, "strength", None),
                        getattr(m, "frequency", None),
                        getattr(m, "duration", None),
                    ]
                    if d
                ]
                lines.append(
                    f"- {name}"
                    + (f" ({', '.join(details)})" if details else "")
                )
            parts.append("Medications:\n" + "\n".join(lines))

        return "\n".join(parts).strip()

    def _truncate(self, text: str, length: int) -> str:
        text = text.strip()
        if len(text) <= length:
            return text
        return text[:length] + "..."

    def _to_datetime(self, value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    def _generate_conversation_id(self, patient_id: str, suffix: str) -> str:
        return f"patient-docs-{suffix}-{patient_id}-{uuid4()}"
