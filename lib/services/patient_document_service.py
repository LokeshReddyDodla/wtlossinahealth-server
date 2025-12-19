import asyncio
from datetime import datetime
import hashlib
from typing import Any, List, Optional
from uuid import uuid4

from bson import ObjectId
from fastapi import UploadFile
from openai import AsyncOpenAI
from lib.core.constants import ProfileTypeEnum
from lib.core.qdrant_store import QdrantStore
from lib.core.types import DocumentTypeLiteral

from lib.services.file_content_extractor import FileContentExtractorService
from lib.services.patient_profile_service import PatientProfileService
from lib.services.ai_conversation_service.ai_conversation_service import (
    AiConversationService,
)
from lib.schemas.patient_document_research import (
    PatientDocumentResearchChatRequest,
    PatientDocumentResearchChatResponse,
    PatientDocumentResearchDocument,
    PatientDocumentResearchSummaryRequest,
    PatientDocumentResearchSummaryResponse,
)
from lib.utils.date_utils import extract_date_from_text
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.s3_utils import upload_file_to_s3

from qdrant_client.http.models import PointStruct

from lib.utils.vector_utils import embed_text


class PatientDocumentService:
    MAX_RESEARCH_DOCUMENTS = 10

    def __init__(
        self,
        qdrant_store: QdrantStore,
        file_content_extractor_service: FileContentExtractorService,
        patient_profile_service: PatientProfileService,
        patient_document_collection: Any,
        patient_document_summary_interactions_collection: Any,
    ):
        self.qdrant_store = qdrant_store
        self.patient_profile_service = patient_profile_service
        self.file_content_extractor_service = file_content_extractor_service
        self.patient_document_collection = patient_document_collection
        self.patient_document_summary_interactions_collection = (
            patient_document_summary_interactions_collection
        )

        self.openai_client = AsyncOpenAI()
        self.s3_bucket_name = "user-assets.aihealth.clinic"
        self.qdrant_collection_name = "patient_data"

    async def fetch_patient_documents(
        self,
        patient_id: str,
        document_type: Optional[str] = None,
        uploaded_by_type: Optional[str] = None,
        order: Optional[str] = "asc",
        limit: Optional[int] = 20,
        offset: int = 0,
    ):
        query: dict = {"patient_id": patient_id}

        if document_type:
            query["category"] = document_type

        if uploaded_by_type:
            query["metadata.uploaded_by.type"] = uploaded_by_type

        sort_order = 1 if order == "asc" else -1

        projection = {
            "text_raw": 0,
            "summary_text": 0,
            "text_repr": 0,
        }

        cursor = (
            self.patient_document_collection.find(query, projection)  # type: ignore
            .sort("metadata.created_at", sort_order)
            .skip(offset)
            .limit(limit)
        )

        docs = await cursor.to_list(length=limit)

        for doc in docs:
            doc["id"] = str(doc["_id"])
            del doc["_id"]

        return docs

    async def generate_research_summary(
        self,
        patient_id: str,
        care_provider_id: str,
        request: PatientDocumentResearchSummaryRequest,
    ) -> PatientDocumentResearchSummaryResponse:
        documents = await self._fetch_documents_by_ids(
            patient_id, request.document_ids
        )
        summary_docs = [
            self._to_summary_document(doc) for doc in documents
        ]
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
        summary_docs = [
            self._to_summary_document(doc) for doc in documents
        ]
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

    async def upload_multiple_documents(
        self,
        patient_id: str,
        files: List[UploadFile],
        document_type: DocumentTypeLiteral,
        uploaded_by_id: str,
        uploaded_by_type: ProfileTypeEnum,
    ):
        tasks = []

        for f in files:
            file_bytes = await f.read()
            tasks.append(
                self.upload_patient_document(
                    patient_id=patient_id,
                    file_bytes=file_bytes,
                    file_name=f.filename,  # type: ignore
                    content_type=f.content_type,  # type: ignore
                    document_type=document_type,
                    uploaded_by_id=uploaded_by_id,
                    uploaded_by_type=uploaded_by_type,
                )
            )

        # Run uploads in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions into readable errors instead of crashing the whole batch
        final = []
        for index, r in enumerate(results):
            if isinstance(r, Exception):
                final.append(
                    {
                        "file_name": files[index].filename,
                        "status": "failed",
                        "error": str(r),
                    }
                )
            else:
                final.append(
                    {
                        "file_name": files[index].filename,
                        "status": "success",
                        "document_id": r,
                    }
                )

        return final

    async def upload_patient_document(
        self,
        patient_id: str,
        file_bytes: bytes,
        file_name: str,
        content_type: str,
        document_type: DocumentTypeLiteral,
        uploaded_by_id: str,
        uploaded_by_type: ProfileTypeEnum,
    ):
        try:
            # Upload file to S3
            file_url = upload_file_to_s3(
                file_bytes=file_bytes,
                bucket_name=self.s3_bucket_name,
                file_name=file_name,
                content_type=content_type,
                folder_path=f"patients/{patient_id}/documents/{document_type}",
            )
            if not file_url:
                raise_http_exception(
                    status_code=400,
                    message="Failed to upload file to S3",
                )

            # Extract text content
            extracted_text = self.file_content_extractor_service.extract(
                file_bytes, file_name, content_type
            )
            if not extracted_text or len(extracted_text.strip()) == 0:
                raise_http_exception(400, "No readable text found in document")

            # Generate summary
            summary_text = await self._summarize_document(extracted_text)

            # Generate text_repr for embedding
            text_repr = await self._generate_text_repr(summary_text)

            # Determine document date
            document_date = (
                extract_date_from_text(summary_text) or datetime.now()
            )

            # Build Mongo document
            mongo_doc = self._build_mongo_document(
                patient_id,
                file_url,
                content_type,
                file_name,
                document_type,
                extracted_text,
                summary_text,
                text_repr,
                uploaded_by_id,
                uploaded_by_type,
                document_date,
            )
            inserted = await self.patient_document_collection.insert_one(mongo_doc)  # type: ignore
            document_id = str(inserted.inserted_id)

            # Fetch patient profile
            profile = await self.patient_profile_service.fetch_patient_profile(
                patient_id
            )

            # Build payload
            payload = self._build_embedding_payload(
                profile,
                document_id,
                file_url,
                file_name,
                content_type,
                document_type,
                summary_text,
                text_repr,
                uploaded_by_id,
                uploaded_by_type,
                document_date,
            )

            await self._upsert_to_qdrant(payload, text_repr, document_id)

            return document_id

        except Exception as e:
            raise_http_exception(
                status_code=500,
                message="Failed to upload patient report",
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

    async def _summarize_document(self, text: str) -> str:
        summary_prompt = f"""
            You are a medical summarization assistant.
            Summarize the following report or prescription clearly and concisely.
            Focus on retaining clinically relevant information such as:
            - Patient details (if available)
            - Report date or test date
            - Doctor name (if mentioned)
            - Diagnoses or complaints
            - Lab test names, values, and units
            - Medications, dosages, and frequency
            - Duration of treatment or follow-up instructions

            Formatting requirements:
            - When mentioning date and time, normalize it into ISO format: YYYY-MM-DDTHH:MM:SS (24-hour time)
            - Keep it factual and structured. Avoid conversational tone.

            Document text:
            {text}
            """

        return await self._complete_text(
            prompt=summary_prompt,
            model="gpt-4o-mini",
        )

    async def _generate_text_repr(self, summary_text: str) -> str:
        repr_prompt = f"""
        You are creating a compact semantic representation of a medical document.
        Convert the following summary into a short, information-dense text for embedding.

        Requirements:
        - Use clear factual language
        - Exclude filler or generic words
        - Emphasize key medical entities: tests, medicines, dosages, findings, values, and diagnoses
        - Aim for one paragraph of 3–5 sentences max

        Summary:
        {summary_text}
        """
        return await self._complete_text(
            prompt=repr_prompt, model="gpt-4o-mini"
        )

    def _build_mongo_document(
        self,
        patient_id: str,
        file_url: str,
        content_type: str,
        file_name: str,
        document_type: str,
        extracted_text: str,
        summary_text: str,
        text_repr: str,
        uploaded_by_id: str,
        uploaded_by_type: ProfileTypeEnum,
        document_date: datetime,
    ) -> dict:
        now = datetime.now()
        return {
            "patient_id": patient_id,
            "file": {
                "url": file_url,
                "type": content_type,
                "name": file_name,
                "uploaded_at": now,
            },
            "category": document_type,
            "text_raw": extracted_text,
            "summary_text": summary_text,
            "text_repr": text_repr,
            "metadata": {
                "uploaded_by": {
                    "id": uploaded_by_id,
                    "type": uploaded_by_type,
                },
                "created_at": now,
                "document_date": document_date,
            },
        }

    def _build_embedding_payload(
        self,
        profile,
        document_id: str,
        file_url: str,
        file_name: str,
        file_content_type: str,
        document_type: str,
        summary_text: str,
        text_repr: str,
        uploaded_by_id: str,
        uploaded_by_type: ProfileTypeEnum,
        document_date: datetime,
    ) -> dict:
        now = datetime.now()
        return {
            "patient_id": str(profile.patient_id),
            "patient_age": profile.age,
            "patient_gender": profile.gender,
            "document_id": document_id,
            "data_type": "patient_document",
            "document_type": document_type,
            "file_name": file_name,
            "file_url": file_url,
            "uploaded_by_type": uploaded_by_type,
            "uploaded_by_id": uploaded_by_id,
            "uploaded_at": int(now.timestamp() * 1000),
            "summary": summary_text,
            "text_repr": text_repr,
            "embedding_metadata": {
                "source": "file_upload",
                "generation_model": "gpt-4o-mini",
                "repr_version": "v1",
            },
            "date": document_date.strftime("%Y-%m-%d"),
            "month": document_date.month,
            "week_number": document_date.isocalendar()[1],
            "day_of_week": document_date.weekday(),
            "is_weekend": document_date.weekday() >= 5,
            "time_of_day_bucket": [self._bucket_time(document_date.hour)],
            "data": {
                "file_content_type": file_content_type,
                "extracted_text_length": len(summary_text),
            },
        }

    async def _upsert_to_qdrant(
        self, payload: dict, text_repr: str, document_id: str
    ):
        embedding = await embed_text(text_repr)
        point_id = hashlib.md5(document_id.encode()).hexdigest()
        async with self.qdrant_store.get_client() as client:
            await client.upsert(
                collection_name=self.qdrant_collection_name,
                points=[
                    PointStruct(id=point_id, vector=embedding, payload=payload)
                ],
            )

    async def _complete_text(self, prompt: str, model: str) -> str:
        response = await self.openai_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content.strip()  # type: ignore

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

    def _bucket_time(self, hour: int) -> str:
        if 6 <= hour < 12:
            return "morning"
        elif 12 <= hour < 18:
            return "afternoon"
        elif 18 <= hour < 24:
            return "evening"
        else:
            return "night"
