import json
from datetime import date, datetime
from typing import Any, List, Optional
from uuid import UUID

from fastapi import status
from markdownify import markdownify as md
from sqlalchemy import asc, delete, desc, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.core.constants import ProfileTypeEnum
from lib.core.postgres_store import PostgresStore
from lib.models.patient_prescription import (
    PatientPrescription as PatientPrescriptionModel,
    PatientPrescriptionMedicine,
)
from lib.schemas.ai_conversation_schemas import (
    AiConversationMessage as AiConversationMessageSchema,
)
from lib.schemas.patient_prescription_analysis import (
    PrescriptionAnalysis,
    PrescriptionStructureResponse,
)
from lib.services.ai_conversation_service.ai_conversation_service import (
    AiConversationService,
)
from lib.services.patient_profile_service import PatientProfileService
from lib.services.prescription_analysis_service import (
    PrescriptionAnalysisService,
)
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session


class PrescriptionService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        prescription_analysis_service: PrescriptionAnalysisService,
        patient_profile_service: PatientProfileService,
    ):
        from lib.dependencies.service_dependencies import (
            get_token_usage_service,
        )

        self.postgres_store = postgres_store
        self.prescription_analysis_service = prescription_analysis_service
        self.patient_profile_service = patient_profile_service
        self.ai_conversation_service = AiConversationService(
            conversation_type="prescription",
            selected_ai_model="gpt-5-mini",
            ai_model_provider="openai",
        )
        self.token_usage_service = get_token_usage_service()

    @with_postgres_session
    async def fetch_prescriptions(
        self,
        patient_id: str,
        source: Optional[str] = None,
        analyzed: Optional[str] = None,
        order: Optional[str] = "asc",
        limit: Optional[int] = None,
        offset: int = 0,
        *,
        postgres_session: AsyncSession,
    ):
        try:
            query = (
                select(PatientPrescriptionModel)
                .where(PatientPrescriptionModel.patient_id == patient_id)
                .options(selectinload(PatientPrescriptionModel.medicines))
            )

            if source:
                query = query.filter(PatientPrescriptionModel.source == source)
            if analyzed == "true":
                query = query.filter(PatientPrescriptionModel.analyzed == True)
            elif analyzed == "false":
                query = query.filter(
                    PatientPrescriptionModel.analyzed == False
                )

            # Add ordering
            if order == "asc":
                query = query.order_by(
                    asc(PatientPrescriptionModel.created_at)
                )
            else:
                query = query.order_by(
                    desc(PatientPrescriptionModel.created_at)
                )

            # Apply offset and limit if provided
            query = query.offset(offset)
            if limit:
                query = query.limit(limit)

            result = await postgres_session.execute(query)
            prescriptions = result.scalars().all()

            return prescriptions
        except Exception as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Internal Server Error",
                detail=str(e),
            )

    @with_postgres_session
    async def fetch_prescription(
        self, prescription_id: str, *, postgres_session: AsyncSession
    ) -> PatientPrescriptionModel:
        query = (
            select(PatientPrescriptionModel)
            .where(PatientPrescriptionModel.prescription_id == prescription_id)
            .options(selectinload(PatientPrescriptionModel.medicines))
        )

        result = await postgres_session.execute(query)
        prescription = result.scalars().first()

        if not prescription:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Prescription not found",
            )

        return prescription

    @with_postgres_session
    async def upload_and_analyze_prescription(
        self,
        prescription_file_url: str,
        patient_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> PatientPrescriptionModel:
        try:
            parsed_ai_response = (
                await self.prescription_analysis_service.analyze_prescription(
                    prescription_file_url,
                    patient_id,
                    ProfileTypeEnum.PATIENT,
                )
            )

            if not parsed_ai_response:
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=f"Failed to be analyze your prescription",
                )

            saved_prescription = await self.save_prescription_analysis(
                patient_id,
                prescription_file_url,
                parsed_ai_response,
                postgres_session=postgres_session,
            )

            refetched_prescription = await self.fetch_prescription(
                str(saved_prescription.prescription_id)
            )

            # Define custom conversation flow for meals
            message_sequence = self._generate_conversation_flow(
                patient_id,
                refetched_prescription,
            )

            # Pass the message sequence to AiConversationService
            await self.ai_conversation_service.add_multiple_messages_to_conversation(
                messages=message_sequence,
            )

            return refetched_prescription
        except json.JSONDecodeError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Invalid JSON",
                detail=str(e),
            )
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def confirm_prescription_analysis(
        self,
        patient_id: str,
        confirmed_prescription: PrescriptionStructureResponse,
        *,
        postgres_session: AsyncSession,
    ) -> PatientPrescriptionModel:
        try:
            # Step 1 — Generate summary
            summary_response = await self.prescription_analysis_service.generate_prescription_summary(
                confirmed_prescription=confirmed_prescription,
                user_id=patient_id,
                user_type=ProfileTypeEnum.PATIENT,
            )

            # Step 2 — Save prescription
            saved_prescription = await self.save_prescription_analysis(
                patient_id,
                confirmed_prescription.prescription_file_url,
                PrescriptionAnalysis(
                    **confirmed_prescription.dict(), **summary_response.dict()
                ),
                postgres_session=postgres_session,
            )

            # Step 3 — Refetch prescription
            refetched_prescription = await self.fetch_prescription(
                str(saved_prescription.prescription_id)
            )

            # Step 3 — Generate conversation flow
            message_sequence = self._generate_conversation_flow(
                patient_id,
                refetched_prescription,
            )

            # Pass the message sequence to AiConversationService
            await self.ai_conversation_service.add_multiple_messages_to_conversation(
                messages=message_sequence,
            )

            return refetched_prescription
        except json.JSONDecodeError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Invalid JSON",
                detail=str(e),
            )
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def save_prescription_analysis(
        self,
        patient_id: UUID,
        prescription_file_url: str,
        analysis_data: PrescriptionAnalysis,
        *,
        postgres_session: AsyncSession,
    ) -> PatientPrescriptionModel:
        # Create the main prescription record
        prescription = PatientPrescriptionModel(
            patient_id=patient_id,
            doctor_name=analysis_data.doctor_name,
            prescription_date=analysis_data.prescription_date,
            prescription_file_url=prescription_file_url,
            analyzed=True,
            general_advice=analysis_data.general_advice,
            follow_up_required=analysis_data.follow_up_required,
            follow_up_in_days=analysis_data.follow_up_in_days,
            overall_summary=analysis_data.overall_summary,
        )

        # Create medicine records
        prescription.medicines = [
            PatientPrescriptionMedicine(
                brand_name=medicine.brand_name,
                generic_name=medicine.generic_name,
                formulation=medicine.formulation,
                strength=medicine.strength,
                frequency=medicine.frequency,
                duration=medicine.duration,
                before_after_food=medicine.before_after_food,
                route=medicine.route,
                instructions=medicine.instructions,
                purpose=medicine.purpose,
                possible_side_effects=medicine.possible_side_effects,
                explanation=medicine.explanation,
            )
            for medicine in analysis_data.medicines
        ]

        # Add to session and commit
        postgres_session.add(prescription)
        await postgres_session.commit()
        await postgres_session.refresh(prescription)

        return prescription

    def _generate_conversation_flow(
        self,
        patient_id: str,
        prescription_data: PatientPrescriptionModel,
    ) -> list[AiConversationMessageSchema]:
        # Markdown summary of prescription
        summary_md = md(
            f"📄 I uploaded a prescription from **{prescription_data.doctor_name}** "
            f"dated **{prescription_data.prescription_date}**.\n\n"
            f"📝 Summary:\n- {prescription_data.overall_summary or 'N/A'}"
        )

        # List of medicines in Markdown format
        medicines_md = "\n\n💊 Medicines Prescribed:\n"
        for med in prescription_data.medicines:
            med_line = "- "

            # Brand name / generic name
            if med.brand_name:
                med_line += f"**{med.brand_name}**"
            elif med.generic_name:
                med_line += f"**{med.generic_name}**"
            else:
                med_line += "**Unnamed Medicine**"

            # Formulation and strength
            details = []
            if med.formulation:
                details.append(med.formulation)
            if med.strength:
                details.append(med.strength)
            if details:
                med_line += f" ({', '.join(details)})"

            # Frequency and duration
            if med.frequency:
                med_line += f", {med.frequency}"
            if med.duration:
                med_line += f", {med.duration}"

            # Before/After food and route
            extra_details = []
            if med.before_after_food:
                extra_details.append(med.before_after_food)
            if med.route:
                extra_details.append(med.route)
            if extra_details:
                med_line += f" — {'; '.join(extra_details)}"

            # Purpose
            if med.purpose:
                med_line += f" (_{med.purpose}_)"

            # Instructions
            if med.instructions:
                med_line += f"\n    📌 Instructions: {med.instructions}"

            medicines_md += f"{med_line}\n"

        return [
            AiConversationMessageSchema(
                user_id=str(patient_id),
                user_type=ProfileTypeEnum.PATIENT,
                conversation_id=str(prescription_data.prescription_id),
                conversation_type="prescription",
                role="human",
                message_type="image",
                content=str(prescription_data.prescription_file_url),
            ),
            AiConversationMessageSchema(
                user_id=str(patient_id),
                user_type=ProfileTypeEnum.PATIENT,
                conversation_id=str(prescription_data.prescription_id),
                conversation_type="prescription",
                role="human",
                message_type="markdown",
                content=summary_md + medicines_md,
            ),
            AiConversationMessageSchema(
                user_id=str(patient_id),
                user_type=ProfileTypeEnum.PATIENT,
                conversation_id=str(prescription_data.prescription_id),
                conversation_type="prescription",
                role="ai",
                message_type="text",
                content="Thanks for sharing the prescription. Let me know if you want help understanding the medicines or follow-up details.",
            ),
        ]

    @with_postgres_session
    async def delete_prescription(
        self,
        prescription_id: UUID,
        patient_id: str,
        *,
        postgres_session: AsyncSession,
    ):
        try:
            result = await postgres_session.execute(
                select(PatientPrescriptionModel).where(
                    PatientPrescriptionModel.prescription_id
                    == prescription_id,
                    PatientPrescriptionModel.patient_id == patient_id,
                )
            )
            prescription = result.scalars().first()

            if not prescription:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Prescription not found.",
                )

            await postgres_session.delete(prescription)
            await postgres_session.commit()

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def delete_all_prescriptions_for_patient(
        self, patient_id: str, *, postgres_session: AsyncSession
    ):
        try:
            await postgres_session.execute(
                delete(PatientPrescriptionModel).where(
                    PatientPrescriptionModel.patient_id == patient_id
                )
            )
            await postgres_session.commit()

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )
