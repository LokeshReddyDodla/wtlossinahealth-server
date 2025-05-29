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
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from fastapi import HTTPException, status


class PatientPackageAssignmentService:
    def __init__(self, postgres_store: PostgresStore):
        self.postgres_store = postgres_store

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
    async def get_active_assignments_for_patient(
        self, patient_id: str, *, postgres_session: AsyncSession
    ) -> list[PatientPackageAssignmentModel]:
        """Get all active package assignments for a patient."""
        try:
            stmt = (
                select(PatientPackageAssignmentModel)
                .where(
                    PatientPackageAssignmentModel.patient_id == patient_id,
                    PatientPackageAssignmentModel.status
                    == PatientPackageAssignmentModel.ACTIVE,
                )
                .options(joinedload(PatientPackageAssignmentModel.package))
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
    async def create_assignment(
        self,
        assignment_data: PatientPackageAssignmentCreate,
        *,
        postgres_session: AsyncSession
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
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Patient already has an active assignment for this package",
                )

            # Create new assignment
            new_assignment = PatientPackageAssignmentModel(
                **assignment_data.model_dump()
            )
            postgres_session.add(new_assignment)
            await postgres_session.commit()
            await postgres_session.refresh(new_assignment)

            return new_assignment

        except SQLAlchemyError as e:
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
        postgres_session: AsyncSession
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

    @with_postgres_session
    async def sync_package_care_providers(
        self, patient_id: str, *, postgres_session: AsyncSession
    ) -> PatientModel:
        """Ensure patient has all care providers from their active packages."""
        try:
            assignments = await self.get_active_assignments_for_patient(
                patient_id, postgres_session=postgres_session
            )

            patient = assignments[0].patient if assignments else None
            if not patient:
                raise_http_exception(
                    404, "Patient not found or has no active packages"
                )

            # Get all unique care providers from all active packages
            package_care_providers = set()
            for assignment in assignments:
                package_care_providers.update(
                    assignment.package.care_providers
                )

            # Get current patient care providers
            current_care_providers = set(patient.care_providers)

            # Add missing care providers
            added = False
            for cp in package_care_providers - current_care_providers:
                patient.care_providers.append(cp)
                added = True

            if added:
                await postgres_session.commit()
                await postgres_session.refresh(patient)

            return patient

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )
