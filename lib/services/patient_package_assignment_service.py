from datetime import timedelta
import logging
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.core.postgres_store import PostgresStore
from lib.models.patient import Patient as PatientModel
from lib.models.patient_package_assignment import (
    AssignmentStatus,
    PatientPackageAssignment as PatientPackageAssignmentModel,
)
from lib.schemas.patient_package_assignment import (
    PatientPackageAssignmentCreate,
)
from lib.services.chat.chat_exceptions import ChatCreationError
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from fastapi import HTTPException, status
from lib.models import Package as PackageModel
from lib.models import CareProvider as CareProviderModel

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class PatientPackageAssignmentService:
    def __init__(
        self,
        patient_service: PatientProfileService,
        postgres_store: PostgresStore,
        package_service,
    ):
        self.patient_service = patient_service
        self.package_service = package_service
        self.postgres_store = postgres_store

    @with_postgres_session
    async def get_assignments_for_patient(
        self,
        patient_id: str,
        health_facility_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> list[PatientPackageAssignmentModel]:
        try:
            stmt = (
                select(PatientPackageAssignmentModel)
                .options(
                    selectinload(
                        PatientPackageAssignmentModel.package
                    ).selectinload(PackageModel.care_providers)
                )
                .join(PatientPackageAssignmentModel.package)
                .where(
                    PatientPackageAssignmentModel.patient_id == patient_id,
                    PackageModel.health_facility_id == health_facility_id,
                )
            )
            result = await postgres_session.execute(stmt)
            return list(result.scalars().all())

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error while fetching patient assignments",
                detail=str(e),
            )

    @with_postgres_session
    async def get_active_assignments_for_package(
        self, package_id: str, *, postgres_session: AsyncSession
    ) -> list[PatientPackageAssignmentModel]:
        """Get all active patient assignments for a package with patients loaded."""
        try:
            stmt = (
                select(PatientPackageAssignmentModel)
                .where(
                    PatientPackageAssignmentModel.package_id == package_id,
                    PatientPackageAssignmentModel.status
                    == PatientPackageAssignmentModel.ACTIVE,
                )
                .options(joinedload(PatientPackageAssignmentModel.patient))
            )
            result = await postgres_session.execute(stmt)
            return list(result.scalars().all())

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def get_active_assignment_for_patient(
        self, patient_id: str, *, postgres_session: AsyncSession
    ) -> Optional[PatientPackageAssignmentModel]:
        """Get active package assignment for a patient."""
        try:
            stmt = (
                select(PatientPackageAssignmentModel)
                .where(
                    PatientPackageAssignmentModel.patient_id == patient_id,
                    PatientPackageAssignmentModel.status
                    == PatientPackageAssignmentModel.ACTIVE,
                )
                .options(joinedload(PatientPackageAssignmentModel.package))
                .limit(1)
            )
            result = await postgres_session.execute(stmt)
            return result.scalars().first()

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def create_assignment(
        self,
        assignment_data: PatientPackageAssignmentCreate,
        *,
        postgres_session: AsyncSession,
    ) -> PatientPackageAssignmentModel:
        try:
            # Check if patient already has an active assignment for this package
            existing_assignment = (
                await self.get_active_assignment_for_patient_and_package(
                    patient_id=assignment_data.patient_id,
                    package_id=assignment_data.package_id,
                    postgres_session=postgres_session,
                )
            )

            if existing_assignment:
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="Patient already has an active assignment for this package",
                )

            patient = await self.patient_service.fetch_patient_profile(
                patient_id=assignment_data.patient_id,
                postgres_session=postgres_session,
            )
            package = await self.package_service.fetch_package(
                package_id=assignment_data.package_id,
                detailed=True,
                postgres_session=postgres_session,
            )

            if not patient or not package:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Patient or package not found",
                )

            # Create new assignment
            calculated_end_date = assignment_data.start_date + timedelta(
                days=package.duration_days
            )
            new_assignment = PatientPackageAssignmentModel(
                **assignment_data.model_dump(exclude={"end_date"}),
                end_date=calculated_end_date,
            )
            postgres_session.add(new_assignment)

            # Assign care providers from package if not already assigned
            added_provider_ids = [
                str(cp.care_provider_id)
                for cp in package.care_providers
                if cp not in patient.care_providers
            ]

            if added_provider_ids:
                await self.patient_service.assign_care_providers_to_patient(
                    patient_id=assignment_data.patient_id,
                    care_provider_ids=added_provider_ids,
                    health_facility_id=str(package.health_facility_id),
                    postgres_session=postgres_session,
                )

            postgres_session.add(patient)
            await postgres_session.flush()
            await postgres_session.refresh(new_assignment)
            await postgres_session.commit()

            return new_assignment

        except ChatCreationError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=500,
                message="Chat creation failed",
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
    async def remove_assignment(
        self,
        assignment_id: str,
        health_facility_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        try:
            assignment = await self._fetch_assignment_with_patient_and_package(
                assignment_id, postgres_session
            )

            patient = assignment.patient
            package = assignment.package

            # Determine care providers that are only linked through this package
            care_provider_ids_to_remove = []
            for care_provider in package.care_providers:
                # Check if the care provider is used in any other assignment for this patient
                other_assignments_stmt = (
                    select(PatientPackageAssignmentModel)
                    .join(PatientPackageAssignmentModel.package)
                    .join(PackageModel.care_providers)
                    .where(
                        PatientPackageAssignmentModel.patient_id
                        == patient.patient_id,
                        PatientPackageAssignmentModel.assignment_id
                        != assignment.assignment_id,
                        CareProviderModel.care_provider_id
                        == care_provider.care_provider_id,
                    )
                    .limit(1)
                )
                other_result = await postgres_session.execute(
                    other_assignments_stmt
                )
                is_used_elsewhere = other_result.scalars().first()

                if (
                    not is_used_elsewhere
                    and care_provider in patient.care_providers
                ):
                    care_provider_ids_to_remove.append(
                        str(care_provider.care_provider_id)
                    )

            # Remove the care providers through proper method
            if care_provider_ids_to_remove:
                await self.patient_service.remove_care_providers_from_patient(
                    patient_id=str(patient.patient_id),
                    care_provider_ids=care_provider_ids_to_remove,
                    health_facility_id=health_facility_id,
                    postgres_session=postgres_session,
                )

            # Delete the assignment
            await postgres_session.delete(assignment)
            postgres_session.add(patient)

            await postgres_session.commit()

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def get_active_assignment_for_patient_and_package(
        self,
        patient_id: UUID,
        package_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> Optional[PatientPackageAssignmentModel]:
        try:
            stmt = select(PatientPackageAssignmentModel).where(
                PatientPackageAssignmentModel.patient_id == patient_id,
                PatientPackageAssignmentModel.package_id == package_id,
                PatientPackageAssignmentModel.status
                == AssignmentStatus.ACTIVE,
            )
            result = await postgres_session.execute(stmt)
            return result.scalars().first()

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    async def _fetch_assignment_with_patient_and_package(
        self,
        assignment_id: str,
        postgres_session: AsyncSession,
    ) -> PatientPackageAssignmentModel:
        stmt = (
            select(PatientPackageAssignmentModel)
            .options(
                selectinload(
                    PatientPackageAssignmentModel.package
                ).selectinload(PackageModel.care_providers),
                selectinload(
                    PatientPackageAssignmentModel.patient
                ).selectinload(PatientModel.care_providers),
            )
            .where(
                PatientPackageAssignmentModel.assignment_id == assignment_id
            )
        )
        result = await postgres_session.execute(stmt)
        assignment = result.scalars().first()

        if not assignment:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Assignment not found.",
            )

        return assignment
