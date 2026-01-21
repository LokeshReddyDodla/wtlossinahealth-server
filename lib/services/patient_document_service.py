import asyncio
from datetime import datetime
import hashlib
from typing import Any, List, Optional
from fastapi import UploadFile
from openai import AsyncOpenAI
from lib.core.constants import ProfileTypeEnum
from lib.core.mongo_store import MongoStore
from lib.core.qdrant_store import QdrantStore
from lib.core.types import DocumentTypeLiteral

from lib.services.file_content_extractor import FileContentExtractorService
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.date_utils import extract_date_from_text
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.s3_utils import upload_file_to_s3

from qdrant_client.http.models import PointStruct

from lib.utils.vector_utils import embed_text


class PatientDocumentService:
    def __init__(
        self,
        qdrant_store: QdrantStore,
        file_content_extractor_service: FileContentExtractorService,
        patient_profile_service: PatientProfileService,
        patient_document_collection: MongoStore,
    ):
        self.qdrant_store = qdrant_store
        self.patient_profile_service = patient_profile_service
        self.file_content_extractor_service = file_content_extractor_service
        self.patient_document_collection = patient_document_collection
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

            is_image = content_type.startswith("image/")
            if not extracted_text or len(extracted_text.strip()) == 0:
                if not is_image:
                    raise_http_exception(
                        400, "No readable text found in document"
                    )
                extracted_text = ""

            summary_text = ""
            text_repr = ""
            if extracted_text:
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

            if text_repr:
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

    def _bucket_time(self, hour: int) -> str:
        if 6 <= hour < 12:
            return "morning"
        elif 12 <= hour < 18:
            return "afternoon"
        elif 18 <= hour < 24:
            return "evening"
        else:
            return "night"
