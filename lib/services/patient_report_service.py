from typing import List, Optional

from sqlalchemy import asc, desc
from lib.core.constants import ProfileTypeEnum
from lib.core.postgres_store import PostgresStore
from lib.core.types import ReportTypeLiteral
from lib.models.patient_report import PatientReport
from lib.services.ai_conversation_service.ai_conversation_service import (
    AiConversationService,
)
from lib.services.file_content_extractor import FileContentExtractorService
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session
from sqlalchemy.ext.asyncio import AsyncSession
from lib.schemas.ai_conversation_schemas import (
    AiConversationMessage as AiConversationMessageSchema,
)
from lib.utils.s3_utils import upload_file_to_s3
from sqlalchemy.future import select
from fastapi import status


class PatientReportService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        file_content_extractor_service: FileContentExtractorService,
        patient_profile_service: PatientProfileService,
    ):
        self.postgres_store = postgres_store
        self.patient_profile_service = patient_profile_service
        self.file_content_extractor_service = file_content_extractor_service
        self.s3_bucket_name = "user-assets.aihealth.clinic"
        self.ai_conversation_service = AiConversationService(
            conversation_type="report",
            selected_ai_model="gpt-4o-mini",
            ai_model_provider="openai",
        )

    @with_postgres_session
    async def fetch_patient_reports(
        self,
        patient_id: str,
        report_type: Optional[ReportTypeLiteral] = None,
        uploaded_by_type: Optional[ProfileTypeEnum] = None,
        order: Optional[str] = "asc",
        limit: Optional[int] = None,
        offset: int = 0,
        *,
        postgres_session: AsyncSession,
    ) -> List[PatientReport]:

        try:
            query = select(PatientReport).where(
                PatientReport.patient_id == patient_id
            )

            if report_type:
                query = query.filter(PatientReport.report_type == report_type)
            if uploaded_by_type:
                query = query.filter(
                    PatientReport.uploaded_by_type == uploaded_by_type
                )

            # Ordering
            if order == "asc":
                query = query.order_by(asc(PatientReport.uploaded_at))
            else:
                query = query.order_by(desc(PatientReport.uploaded_at))

            # Pagination
            query = query.offset(offset)
            if limit:
                query = query.limit(limit)

            result = await postgres_session.execute(query)
            reports = result.scalars().all()
            return list(reports)

        except Exception as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch patient reports",
                detail=str(e),
            )

    @with_postgres_session
    async def upload_patient_report(
        self,
        patient_id: str,
        file_bytes: bytes,
        file_name: str,
        content_type: str,
        report_type: ReportTypeLiteral,
        uploaded_by_id: str,
        uploaded_by_type: ProfileTypeEnum,
        *,
        postgres_session: AsyncSession,
    ) -> PatientReport:
        try:
            file_url = upload_file_to_s3(
                file_bytes=file_bytes,
                bucket_name=self.s3_bucket_name,
                file_name=file_name,
                content_type=content_type,
                folder_path=f"patients/{patient_id}/reports/{report_type}",
            )
            if not file_url:
                raise_http_exception(
                    status_code=400,
                    message="Failed to upload file to S3",
                )

            # Extract content
            content_extracted = self.file_content_extractor_service.extract(
                file_bytes, file_name, content_type
            )

            report = PatientReport(
                patient_id=patient_id,
                file_name=file_name,
                file_type=content_type,
                uploaded_by_id=uploaded_by_id,
                uploaded_by_type=uploaded_by_type,
                report_type=report_type,
                file_url=file_url or "",
                content_extracted=content_extracted,
            )

            postgres_session.add(report)
            await postgres_session.commit()
            await postgres_session.refresh(report)

            conversation_ids = {
                "patient": f"{report.report_id}-patient",
                "care_provider": f"{report.report_id}-{uploaded_by_id}",
            }
            messages = [
                AiConversationMessageSchema(
                    user_id=patient_id,
                    user_type=ProfileTypeEnum.PATIENT,
                    conversation_id=conv_id,
                    conversation_type="report",
                    role="human",
                    message_type="text",
                    content=content_extracted,
                    exclude_from_frontend=True,
                )
                for conv_id in conversation_ids.values()
            ]

            await self.ai_conversation_service.add_multiple_messages_to_conversation(
                messages=messages
            )

            await self.ai_conversation_service.generate_response(
                patient_id=patient_id,
                user_id=uploaded_by_id,
                conversation_id=conversation_ids["care_provider"],
                human_input="Summarize this report",
                conversation_type="report",
            )

            return report
        except Exception as e:
            raise_http_exception(
                status_code=500,
                message="Failed to upload patient report",
            )
