from datetime import datetime
from typing import Any, List, Optional
from uuid import uuid4

from bson import ObjectId

from lib.schemas.patient_document_research import (
    PatientDocumentResearchChatRequest,
    PatientDocumentResearchChatResponse,
    PatientDocumentResearchDocument,
    PatientDocumentResearchSummaryRequest,
    PatientDocumentResearchSummaryResponse,
)
from lib.services.ai_conversation_service.ai_conversation_service import (
    AiConversationService,
)
from lib.utils.http_exceptions import raise_http_exception


class PatientDocumentResearchService:
    MAX_RESEARCH_DOCUMENTS = 10

    def __init__(
        self,
        patient_document_collection: Any,
        patient_document_summary_interactions_collection: Any,
    ):
        self.patient_document_collection = patient_document_collection
        self.patient_document_summary_interactions_collection = (
            patient_document_summary_interactions_collection
        )

    async def generate_research_summary(
        self,
        patient_id: str,
        care_provider_id: str,
        request: PatientDocumentResearchSummaryRequest,
    ) -> PatientDocumentResearchSummaryResponse:
        documents = await self._fetch_documents_by_ids(
            patient_id, request.document_ids
        )
        summary_docs = [self._to_summary_document(doc) for doc in documents]
        conversation_id = (
            request.conversation_id
            if request.conversation_id
            else f"patient-docs-{patient_id}-{uuid4()}"
        )

        ai_service = AiConversationService(
            conversation_type="care-provider",
            ai_model_provider="openai",
            selected_ai_model="gpt-4o",
        )

        human_input = (
            "Provide a clinical research summary for the selected patient documents. "
            "Highlight diagnoses, abnormal values, medications, and follow-up actions."
        )
        if request.question:
            human_input += f"\nDoctor question: {request.question}"

        ai_response = await ai_service.generate_response(
            patient_id=patient_id,
            user_id=care_provider_id,
            conversation_id=conversation_id,
            human_input=human_input,
            conversation_type="care-provider",
            additional_context=self._build_patient_document_context(
                documents=summary_docs,
                context_type="patient_document_research",
            ),
        )

        summary_text = ai_response.get(
            "content", "Unable to generate a summary at this time."
        )
        follow_up_questions = ai_response.get("follow_up_questions", []) or []

        await self._record_patient_document_interaction(
            interaction_type="patient_document_research",
            patient_id=patient_id,
            care_provider_id=care_provider_id,
            conversation_id=conversation_id,
            document_ids=request.document_ids,
            question=request.question,
            response_text=summary_text,
            follow_up_questions=follow_up_questions,
            source_documents=summary_docs,
        )

        return PatientDocumentResearchSummaryResponse(
            conversation_id=conversation_id,
            summary=summary_text,
            follow_up_questions=follow_up_questions,
            source_documents=summary_docs,
        )

    async def chat_about_documents(
        self,
        patient_id: str,
        care_provider_id: str,
        request: PatientDocumentResearchChatRequest,
    ) -> PatientDocumentResearchChatResponse:
        documents = await self._fetch_documents_by_ids(
            patient_id, request.document_ids
        )
        summary_docs = [self._to_summary_document(doc) for doc in documents]
        conversation_id = (
            request.conversation_id
            if request.conversation_id
            else f"patient-docs-chat-{patient_id}-{uuid4()}"
        )

        ai_service = AiConversationService(
            conversation_type="care-provider",
            ai_model_provider="openai",
            selected_ai_model="gpt-4o",
        )

        ai_response = await ai_service.generate_response(
            patient_id=patient_id,
            user_id=care_provider_id,
            conversation_id=conversation_id,
            human_input=request.question,
            conversation_type="care-provider",
            additional_context=self._build_patient_document_context(
                documents=summary_docs,
                context_type="patient_document_chat",
            ),
        )

        answer_text = ai_response.get(
            "content", "I'm unable to answer that at the moment."
        )
        follow_up_questions = ai_response.get("follow_up_questions", []) or []

        await self._record_patient_document_interaction(
            interaction_type="patient_document_chat",
            patient_id=patient_id,
            care_provider_id=care_provider_id,
            conversation_id=conversation_id,
            document_ids=request.document_ids,
            question=request.question,
            response_text=answer_text,
            follow_up_questions=follow_up_questions,
            source_documents=summary_docs,
        )

        return PatientDocumentResearchChatResponse(
            conversation_id=conversation_id,
            answer=answer_text,
            follow_up_questions=follow_up_questions,
            source_documents=summary_docs,
        )

    async def _fetch_documents_by_ids(
        self, patient_id: str, document_ids: List[str]
    ) -> List[dict]:
        normalized_ids = self._validate_document_ids(document_ids)

        object_ids = [ObjectId(doc_id) for doc_id in normalized_ids]
        cursor = self.patient_document_collection.find(  # type: ignore
            {"patient_id": patient_id, "_id": {"$in": object_ids}}
        )
        docs = await cursor.to_list(length=len(object_ids))

        docs_by_id = {str(doc["_id"]): doc for doc in docs}
        missing = [doc_id for doc_id in normalized_ids if doc_id not in docs_by_id]
        if missing:
            raise_http_exception(
                status_code=404,
                message="One or more documents were not found for the patient",
                detail={"missing_document_ids": missing},
            )

        return [docs_by_id[doc_id] for doc_id in normalized_ids]

    def _validate_document_ids(self, document_ids: List[str]) -> List[str]:
        if not document_ids:
            raise_http_exception(
                status_code=400,
                message="At least one document must be selected",
            )

        if len(document_ids) > self.MAX_RESEARCH_DOCUMENTS:
            raise_http_exception(
                status_code=400,
                message=(
                    f"A maximum of {self.MAX_RESEARCH_DOCUMENTS} documents can be processed at once"
                ),
            )

        normalized_ids: List[str] = []
        for doc_id in document_ids:
            if not ObjectId.is_valid(doc_id):
                raise_http_exception(
                    status_code=400,
                    message=f"Invalid document ID: {doc_id}",
                )
            normalized_ids.append(str(doc_id))

        return normalized_ids

    def _to_summary_document(self, doc: dict) -> PatientDocumentResearchDocument:
        metadata = doc.get("metadata", {}) or {}
        uploaded_info = metadata.get("uploaded_by", {}) or {}
        file_info = doc.get("file", {}) or {}

        summary_text = (doc.get("summary_text") or doc.get("text_raw") or "").strip()
        if len(summary_text) > 4000:
            summary_text = summary_text[:4000] + "..."

        preview = summary_text[:280]
        if len(summary_text) > 280:
            preview += "..."

        return PatientDocumentResearchDocument(
            document_id=str(doc.get("_id")),
            file_name=file_info.get("name"),
            file_url=file_info.get("url"),
            mime_type=file_info.get("type"),
            category=doc.get("category"),
            document_date=metadata.get("document_date"),
            uploaded_at=file_info.get("uploaded_at"),
            uploaded_by_type=uploaded_info.get("type"),
            summary_preview=preview,
            summary_text=summary_text,
        )

    def _build_patient_document_context(
        self,
        documents: List[PatientDocumentResearchDocument],
        context_type: str,
    ) -> dict:
        return {
            "context_type": context_type,
            "documents": [doc.model_dump() for doc in documents],
        }

    async def _record_patient_document_interaction(
        self,
        interaction_type: str,
        patient_id: str,
        care_provider_id: str,
        conversation_id: str,
        document_ids: List[str],
        question: Optional[str],
        response_text: str,
        follow_up_questions: List[str],
        source_documents: List[PatientDocumentResearchDocument],
    ):
        interaction_doc = {
            "patient_id": patient_id,
            "care_provider_id": care_provider_id,
            "conversation_id": conversation_id,
            "interaction_type": interaction_type,
            "document_ids": document_ids,
            "question": question,
            "response": response_text,
            "follow_up_questions": follow_up_questions,
            "source_documents": [
                doc.model_dump() for doc in source_documents
            ],
            "created_at": datetime.now(),
        }

        await self.patient_document_summary_interactions_collection.insert_one(  # type: ignore
            interaction_doc
        )
