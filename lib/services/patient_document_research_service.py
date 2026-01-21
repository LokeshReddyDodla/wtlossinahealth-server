from datetime import datetime
import inspect as py_inspect
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from bson import ObjectId
from fastapi import HTTPException

from sqlalchemy import asc, desc, inspect, select

from lib.schemas.patient_document_research import (
    PatientDocumentResearchChatRequest,
    PatientDocumentResearchChatResponse,
    PatientDocumentResearchDocument,
    PatientDocumentResearchSelectionItem,
    PatientDocumentResearchSelectionResponse,
    PatientDocumentResearchSource,
    PatientDocumentResearchSummaryRequest,
    PatientDocumentResearchSummaryResponse,
)
from lib.services.ai_conversation_service.ai_conversation_service import (
    AiConversationService,
)
from lib.services.patient_document_service import PatientDocumentService
from lib.services.prescription_service import PrescriptionService
from lib.services.token_usage_service import TokenUsageService
from lib.services.weight_loss_agent_service import WeightLossAgentService
from lib.utils.http_exceptions import raise_http_exception
from lib.models.patient_prescription import (
    PatientPrescription as PatientPrescriptionModel,
)


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
        prescription_service: PrescriptionService,
        weight_loss_agent_service: WeightLossAgentService,
        token_usage_service: TokenUsageService,
    ):
        self.patient_document_collection = patient_document_collection
        self.interactions_collection = (
            patient_document_summary_interactions_collection
        )
        self.patient_document_service = patient_document_service
        self.prescription_service = prescription_service
        self.weight_loss_agent_service = weight_loss_agent_service
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
        inbody_item = await self._get_inbody_selection_item(patient_id)

        items = [self._map_document_to_selection(d) for d in documents]
        items += [self._map_prescription_to_selection(p) for p in prescriptions]
        if inbody_item:
            items.append(inbody_item)

        return PatientDocumentResearchSelectionResponse(items=items)

    async def generate_research_summary(
        self,
        patient_id: str,
        care_provider_id: str,
        request: PatientDocumentResearchSummaryRequest,
    ) -> PatientDocumentResearchSummaryResponse:
        """Generate AI research summary from selected documents."""
        sources = self._normalize_sources(request)
        documents = await self._fetch_source_documents(patient_id, sources)
        conversation_id = request.conversation_id or self._generate_conversation_id(
            patient_id, "research"
        )

        prompt = (
            "Provide a clinical research summary for the selected patient records "
            "(documents, prescriptions, and inbody reports). "
            "Highlight diagnoses, abnormal values, medications, and follow-up actions."
        )
        if request.question:
            prompt += f"\nDoctor question: {request.question}"

        ai_response = await self._get_ai_response(
            patient_id,
            care_provider_id,
            conversation_id,
            prompt,
            documents,
            api_endpoint="/care_provider/patients/documents/research/summary",
        )

        await self._record_interaction(
            "research", patient_id, care_provider_id, conversation_id,
            sources, request.question, ai_response, documents
        )

        return PatientDocumentResearchSummaryResponse(
            conversation_id=conversation_id,
            summary=ai_response["content"],
            follow_up_questions=ai_response["follow_up_questions"],
            source_documents=documents,
        )

    async def chat_about_documents(
        self,
        patient_id: str,
        care_provider_id: str,
        request: PatientDocumentResearchChatRequest,
    ) -> PatientDocumentResearchChatResponse:
        """Answer questions about selected documents."""
        sources = self._normalize_sources(request)
        documents = await self._fetch_source_documents(patient_id, sources)
        conversation_id = request.conversation_id or self._generate_conversation_id(
            patient_id, "chat"
        )

        ai_response = await self._get_ai_response(
            patient_id,
            care_provider_id,
            conversation_id,
            request.question,
            documents,
            api_endpoint="/care_provider/patients/documents/research/chat",
        )

        await self._record_interaction(
            "chat", patient_id, care_provider_id, conversation_id,
            sources, request.question, ai_response, documents
        )

        return PatientDocumentResearchChatResponse(
            conversation_id=conversation_id,
            answer=ai_response["content"],
            follow_up_questions=ai_response["follow_up_questions"],
            source_documents=documents,
        )

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

    async def _get_inbody_selection_item(
        self, patient_id: str
    ) -> Optional[PatientDocumentResearchSelectionItem]:
        try:
            patient_uuid = UUID(patient_id)
        except ValueError:
            return None

        enrollment = await self.weight_loss_agent_service.get_patient_enrollment_by_patient_id(
            patient_uuid
        )
        if not enrollment or not enrollment.get("enrollment_id"):
            return None

        enrollment_id = str(enrollment["enrollment_id"])
        report = await self.weight_loss_agent_service.get_latest_inbody_report_with_details(
            UUID(enrollment_id)
        )
        if not report:
            return None

        report_data = report.get("report") or {}
        highlights = report.get("highlights") or {}
        summary = report_data.get("ai_summary") or ""

        return PatientDocumentResearchSelectionItem(
            source_type="inbody_report",
            source_id=enrollment_id,
            title=report_data.get("original_filename") or "Inbody Report",
            category="inbody_report",
            document_date=report_data.get("report_date"),
            summary_preview=self._truncate(summary, self.PREVIEW_LENGTH) or None,
            metadata={
                "report_id": report_data.get("report_id"),
                "highlights": highlights,
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

    def _map_inbody_to_research(
        self, report_data: Dict[str, Any]
    ) -> PatientDocumentResearchDocument:
        report = report_data.get("report") or {}
        highlights = report_data.get("highlights") or {}
        summary = (report.get("ai_summary") or "").strip()
        if not summary:
            summary = self._build_inbody_summary(highlights)

        return PatientDocumentResearchDocument(
            source_type="inbody_report",
            document_id=str(report.get("report_id") or ""),
            file_name=report.get("original_filename"),
            file_url=None,
            mime_type=report.get("content_type"),
            category="inbody_report",
            document_date=report.get("report_date"),
            uploaded_at=report.get("created_at") or report.get("extracted_at"),
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
        try:
            return await self.prescription_service.fetch_prescriptions(
                patient_id=patient_id,
                order=order,
            )
        except HTTPException as exc:
            if self._is_medicine_schema_mismatch(exc):
                return await self._fetch_prescriptions_without_medicines(
                    patient_id=patient_id,
                    order=order,
                )
            raise

    async def _fetch_prescriptions_without_medicines(
        self,
        patient_id: str,
        order: Optional[str] = "asc",
    ) -> List[Any]:
        async with self.prescription_service.postgres_store.get_session() as session:
            query = select(PatientPrescriptionModel).where(
                PatientPrescriptionModel.patient_id == patient_id
            )
            if order == "asc":
                query = query.order_by(
                    asc(PatientPrescriptionModel.created_at)
                )
            else:
                query = query.order_by(
                    desc(PatientPrescriptionModel.created_at)
                )
            result = await session.execute(query)
            return result.scalars().all()

    def _is_medicine_schema_mismatch(self, exc: HTTPException) -> bool:
        detail = ""
        if isinstance(exc.detail, dict):
            detail = str(exc.detail.get("detail", "")).lower()
        else:
            detail = str(exc.detail).lower()
        return (
            "patient_prescription_medicines" in detail
            and "does not exist" in detail
        )

    async def _fetch_source_documents(
        self, patient_id: str, sources: List[PatientDocumentResearchSource]
    ) -> List[PatientDocumentResearchDocument]:
        doc_sources = [s for s in sources if s.source_type == "patient_document"]
        rx_sources = [s for s in sources if s.source_type == "prescription"]
        inbody_sources = [s for s in sources if s.source_type == "inbody_report"]

        doc_map: Dict[str, PatientDocumentResearchDocument] = {}
        rx_map: Dict[str, PatientDocumentResearchDocument] = {}
        inbody_map: Dict[str, PatientDocumentResearchDocument] = {}

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

        # Fetch inbody reports
        if inbody_sources:
            missing = []
            for source in inbody_sources:
                try:
                    enrollment_uuid = UUID(source.source_id)
                except ValueError:
                    raise_http_exception(400, f"Invalid enrollment ID: {source.source_id}")

                report = await self.weight_loss_agent_service.get_latest_inbody_report_with_details(
                    enrollment_uuid
                )
                if not report:
                    missing.append(source.source_id)
                    continue

                report_patient = report.get("report", {}).get("patient_id")
                if report_patient and str(report_patient) != patient_id:
                    missing.append(source.source_id)
                    continue

                inbody_map[source.source_id] = self._map_inbody_to_research(report)

            if missing:
                raise_http_exception(404, "Inbody reports not found", {"ids": missing})

        # Build ordered result preserving source order
        result = []
        for source in sources:
            if source.source_type == "patient_document":
                doc = doc_map.get(source.source_id)
            elif source.source_type == "prescription":
                doc = rx_map.get(source.source_id)
            else:
                doc = inbody_map.get(source.source_id)
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

    async def _get_ai_response(
        self,
        patient_id: str,
        care_provider_id: str,
        conversation_id: str,
        prompt: str,
        documents: List[PatientDocumentResearchDocument],
        api_endpoint: str,
    ) -> Dict[str, Any]:
        ai_service = AiConversationService(
            conversation_type="care-provider",
            ai_model_provider="openai",
            selected_ai_model="gpt-4o",
        )

        generate_kwargs = {
            "patient_id": patient_id,
            "user_id": care_provider_id,
            "conversation_id": conversation_id,
            "human_input": prompt,
            "conversation_type": "care-provider",
            "additional_context": {
                "context_type": "patient_document_research",
                "documents": [d.model_dump() for d in documents],
            },
        }

        signature = py_inspect.signature(ai_service.generate_response)
        if "api_endpoint" in signature.parameters:
            generate_kwargs["api_endpoint"] = api_endpoint

        response = await ai_service.generate_response(**generate_kwargs)

        return {
            "content": response.get("content", "Unable to generate response."),
            "follow_up_questions": response.get("follow_up_questions") or [],
        }

    async def _record_interaction(
        self,
        interaction_type: str,
        patient_id: str,
        care_provider_id: str,
        conversation_id: str,
        sources: List[PatientDocumentResearchSource],
        question: Optional[str],
        ai_response: Dict[str, Any],
        documents: List[PatientDocumentResearchDocument],
    ):
        await self.interactions_collection.insert_one({
            "patient_id": patient_id,
            "care_provider_id": care_provider_id,
            "conversation_id": conversation_id,
            "interaction_type": interaction_type,
            "sources": [s.model_dump() for s in sources],
            "question": question,
            "response": ai_response["content"],
            "follow_up_questions": ai_response["follow_up_questions"],
            "source_documents": [d.model_dump() for d in documents],
            "created_at": datetime.now(),
        })

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

    def _build_inbody_summary(self, highlights: Dict[str, Any]) -> str:
        if not highlights:
            return ""

        labels = {
            "skeletal_muscle_mass": "Skeletal muscle mass",
            "body_fat_percentage": "Body fat percentage",
            "visceral_fat_level": "Visceral fat level",
            "basal_metabolic_rate": "Basal metabolic rate",
        }

        lines = []
        for key, label in labels.items():
            if line := self._format_measurement(label, highlights.get(key)):
                lines.append(line)

        segments = highlights.get("segment_lean_analysis") or []
        segment_lines = []
        for seg in segments:
            if isinstance(seg, dict):
                if line := self._format_measurement(seg.get("label", "Segment"), seg):
                    segment_lines.append(line)
        if segment_lines:
            lines.append("Segmental lean analysis:\n" + "\n".join(segment_lines))

        return "Inbody report highlights:\n" + "\n".join(lines) if lines else ""

    def _format_measurement(self, label: str, data: Any) -> Optional[str]:
        if not data or not isinstance(data, dict):
            return None
        value = data.get("value")
        if value is None:
            return None
        unit = data.get("unit")
        return f"{label}: {value} {unit}" if unit else f"{label}: {value}"

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
