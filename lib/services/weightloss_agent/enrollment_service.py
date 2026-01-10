"""Enrollment-related mixin for weight loss agent workflows."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import status
from sqlalchemy import and_
from sqlalchemy.future import select

from lib.models.care_provider import CareProvider
from lib.models.weight_loss_agent import WeightLossAgentEnrollment
from lib.schemas.weight_loss_agent import (
    WeightLossEnrollmentCreate,
    WeightLossEnrollmentUpdate,
)
from lib.utils.http_exceptions import raise_http_exception


class EnrollmentMixin:
    def _serialize_enrollment(
        self, enrollment: WeightLossAgentEnrollment
    ) -> Dict[str, Any]:
        return {
            "enrollment_id": str(enrollment.enrollment_id),
            "patient_id": str(enrollment.patient_id),
            "enrolled_by_care_provider_id": str(
                enrollment.enrolled_by_care_provider_id
            ),
            "enrollment_date": enrollment.enrollment_date,
            "is_active": enrollment.is_active,
            "program_goals": enrollment.program_goals,
            "target_weight_kg": enrollment.target_weight_kg,
            "target_bmi": enrollment.target_bmi,
            "created_at": enrollment.created_at,
            "updated_at": enrollment.updated_at,
        }

    async def enroll_patient_in_weight_loss_program(
        self,
        enrollment_data: WeightLossEnrollmentCreate,
    ) -> Dict:
        """Enroll a patient in the weight loss program (doctor only) - stores in PostgreSQL"""

        # Ensure care provider exists and is a doctor via profile service
        care_provider = (
            await self.care_provider_profile_service.fetch_care_provider(
                str(enrollment_data.enrolled_by_care_provider_id)
            )
        )
        if str(care_provider.role).lower() != "doctor":
            raise_http_exception(
                status_code=status.HTTP_403_FORBIDDEN,
                message="Only doctors can enroll patients in weight loss program",
            )

        # Ensure patient exists via profile service (raises if missing)
        await self.patient_profile_service.fetch_patient_profile(
            str(enrollment_data.patient_id)
        )

        async with self.postgres_store.get_session() as session:
            # Verify the care provider is a doctor
            care_provider = await session.get(
                CareProvider, enrollment_data.enrolled_by_care_provider_id
            )
            if not care_provider:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Care provider not found",
                )

            if str(care_provider.role).lower() != "doctor":
                raise_http_exception(
                    status_code=status.HTTP_403_FORBIDDEN,
                    message="Only doctors can enroll patients in weight loss program",
                )

            # Check if patient already has an active enrollment in PostgreSQL
            existing_enrollment_result = await session.execute(
                select(WeightLossAgentEnrollment).where(
                    and_(
                        WeightLossAgentEnrollment.patient_id
                        == enrollment_data.patient_id,
                        WeightLossAgentEnrollment.is_active == True,
                    )
                )
            )
            existing_enrollment = existing_enrollment_result.scalar_one_or_none()

            if existing_enrollment:
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="Patient is already enrolled in weight loss program",
                )

            # Create new enrollment in PostgreSQL
            enrollment = WeightLossAgentEnrollment(
                patient_id=enrollment_data.patient_id,
                enrolled_by_care_provider_id=enrollment_data.enrolled_by_care_provider_id,
                enrollment_date=datetime.now(),
                is_active=True,
                program_goals=enrollment_data.program_goals,
                target_weight_kg=enrollment_data.target_weight_kg,
                target_bmi=enrollment_data.target_bmi,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            session.add(enrollment)
            await session.commit()
            await session.refresh(enrollment)

            return self._serialize_enrollment(enrollment)

    async def update_patient_enrollment(
        self,
        enrollment_id: UUID,
        update_data: WeightLossEnrollmentUpdate,
    ) -> Dict:
        """Update patient enrollment details - PostgreSQL"""

        async with self.postgres_store.get_session() as session:
            # Get enrollment from PostgreSQL
            enrollment = await session.get(WeightLossAgentEnrollment, enrollment_id)

            if not enrollment:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Enrollment not found",
                )

            # Update fields
            update_dict = update_data.model_dump(exclude_unset=True)
            for field, value in update_dict.items():
                setattr(enrollment, field, value)
            enrollment.updated_at = datetime.now()

            await session.commit()
            await session.refresh(enrollment)

            return self._serialize_enrollment(enrollment)

    async def get_patient_enrollment(
        self, enrollment_id: UUID
    ) -> Optional[Dict]:
        """Get patient's weight loss enrollment by enrollment_id - PostgreSQL"""

        async with self.postgres_store.get_session() as session:
            enrollment = await session.get(WeightLossAgentEnrollment, enrollment_id)

            if enrollment:
                return self._serialize_enrollment(enrollment)

            return None

    async def get_patient_enrollment_by_patient_id(
        self, patient_id: UUID
    ) -> Optional[Dict]:
        """Get patient's active weight loss enrollment by patient_id - PostgreSQL"""

        async with self.postgres_store.get_session() as session:
            result = await session.execute(
                select(WeightLossAgentEnrollment).where(
                    and_(
                        WeightLossAgentEnrollment.patient_id == patient_id,
                        WeightLossAgentEnrollment.is_active == True,
                    )
                )
            )
            enrollment = result.scalar_one_or_none()

            if enrollment:
                return self._serialize_enrollment(enrollment)

            return None
