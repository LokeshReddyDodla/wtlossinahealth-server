from datetime import date
import random
import string
from typing import List, Optional

from fastapi import status
from sqlalchemy import UUID, distinct, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.core.postgres_store import PostgresStore
from lib.models.package import Package as PackageModel

from lib.schemas.package import PackageCreate, PackageUpdate
from lib.services.care_provider_profile_service import (
    CareProviderProfileService,
)
from lib.services.chat.chat_management_service import ChatManagementService
from lib.services.chat.chat_notification_service import ChatNotificationService
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session
from sqlalchemy.orm import joinedload, selectinload
from lib.models.patient_package_assignment import (
    AssignmentStatus,
    PatientPackageAssignment as PatientPackageAssignmentModel,
)


class PackageService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        patient_service: PatientProfileService,
        care_provider_service: CareProviderProfileService,
        chat_notification_service: ChatNotificationService,
        chat_management_service: ChatManagementService,
    ):
        self.postgres_store = postgres_store
        self.patient_service = patient_service
        self.care_provider_service = care_provider_service
        self.chat_notification_service = chat_notification_service
        self.chat_management_service = chat_management_service

    @with_postgres_session
    async def generate_unique_code(
        self, *, postgres_session: AsyncSession
    ) -> str:
        while True:
            code = "".join(
                random.choices(string.ascii_uppercase + string.digits, k=6)
            )
            stmt = select(PackageModel).where(PackageModel.code == code)
            result = await postgres_session.execute(stmt)
            if not result.scalars().first():
                return code

    @with_postgres_session
    async def fetch_package(
        self,
        package_id: str,
        detailed: Optional[bool] = False,
        *,
        postgres_session: AsyncSession,
    ) -> PackageModel:
        try:
            stmt = select(PackageModel).where(
                PackageModel.package_id == package_id
            )

            if detailed:
                stmt = stmt.options(
                    selectinload(PackageModel.health_facility),
                    selectinload(PackageModel.care_providers),
                    selectinload(PackageModel.patient_assignments).options(
                        joinedload(PatientPackageAssignmentModel.package),
                        joinedload(PatientPackageAssignmentModel.patient),
                    ),
                )

            package = (await postgres_session.execute(stmt)).scalars().first()

            if not package:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Package not found.",
                )

            return package

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def fetch_package_by_code(
        self,
        package_code: str,
        detailed: Optional[bool] = False,
        *,
        postgres_session: AsyncSession,
    ) -> PackageModel:
        try:
            stmt = select(PackageModel).where(
                PackageModel.code == package_code
            )

            if detailed:
                stmt = stmt.options(
                    selectinload(PackageModel.health_facility),
                    selectinload(PackageModel.care_providers),
                )

            package = (await postgres_session.execute(stmt)).scalars().first()

            if not package:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Package not found with the provided code.",
                )

            return package

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def fetch_packages(
        self,
        health_facility_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        *,
        postgres_session: AsyncSession,
    ) -> List[PackageModel]:
        try:
            stmt = select(PackageModel).options(
                selectinload(PackageModel.health_facility),
                selectinload(PackageModel.care_providers),
                selectinload(PackageModel.patient_assignments).options(
                    joinedload(PatientPackageAssignmentModel.package),
                    joinedload(PatientPackageAssignmentModel.patient),
                ),
            )

            if health_facility_id:
                stmt = stmt.where(PackageModel.health_facility_id == health_facility_id)

            if offset:
                stmt = stmt.offset(offset)
            
            if limit:
                stmt = stmt.limit(limit)

            packages = (await postgres_session.execute(stmt)).scalars().all()
            return list(packages)

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def count_packages(
        self,
        health_facility_id: Optional[str] = None,
        *,
        postgres_session: AsyncSession,
    ) -> int:
        try:
            stmt = select(func.count(distinct(PackageModel.package_id)))

            if health_facility_id:
                stmt = stmt.where(PackageModel.health_facility_id == health_facility_id)

            result = await postgres_session.execute(stmt)
            count = result.scalar() or 0

            return count

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def create_package(
        self,
        package_data: PackageCreate,
        health_facility_id: UUID,
        created_by_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> PackageModel:
        try:
            care_provider = (
                await self.care_provider_service.fetch_care_provider(
                    str(created_by_id)
                )
            )
            care_provider = await postgres_session.merge(care_provider)

            code = await self.generate_unique_code(postgres_session=postgres_session)  # type: ignore
            new_package = PackageModel(
                **package_data.model_dump(),
                code=code,
                health_facility_id=health_facility_id,
                created_by=care_provider,
            )
            new_package.care_providers.append(care_provider)

            postgres_session.add(new_package)
            await postgres_session.commit()
            await postgres_session.refresh(new_package)

            return new_package

        except IntegrityError as e:
            await postgres_session.rollback()
            if "uq_package_name_per_health_facility" in str(e.orig):
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="A package with this name already exists for the specified health facility.",
                )

            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Integrity error occurred while creating the package.",
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
    async def update_package(
        self,
        package_id: str,
        updates: PackageUpdate,
        *,
        postgres_session: AsyncSession,
    ) -> PackageModel:
        try:
            package = await self.fetch_package(
                package_id, postgres_session=postgres_session
            )

            for key, value in updates.model_dump(exclude_unset=True).items():
                setattr(package, key, value)

            postgres_session.add(package)
            await postgres_session.commit()
            await postgres_session.refresh(package)

            return package

        except IntegrityError:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Package already exists.",
            )

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def delete_package(
        self,
        package_id: str,
        health_facility_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        try:
            package = await self.fetch_package(
                package_id, postgres_session=postgres_session
            )

            if str(package.health_facility_id) != health_facility_id:
                raise_http_exception(
                    status_code=status.HTTP_403_FORBIDDEN,
                    message="You do not have permission to delete this package as it belongs to a different health facility.",
                )

            await postgres_session.delete(package)
            await postgres_session.commit()

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def assign_care_provider_to_package(
        self,
        package_id: str,
        care_provider_id: str,
        health_facility_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> PackageModel:
        try:
            package = await self.fetch_package(
                package_id, detailed=True, postgres_session=postgres_session
            )
            care_provider = (
                await self.care_provider_service.fetch_care_provider(
                    care_provider_id
                )
            )
            care_provider = await postgres_session.merge(care_provider)

            # Ensure the care provider and package belong to the same health facility
            if package.health_facility_id != care_provider.health_facility_id:  # type: ignore
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="Care Provider and Package belong to different health facilities.",
                )

            # Prevent duplicate assignment
            if care_provider in package.care_providers:
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="Care Provider is already assigned to this package.",
                )

            # Assign care provider to package
            package.care_providers.append(care_provider)

            # Collect patient IDs from assignments
            patient_ids = [
                str(assignment.patient_id)
                for assignment in package.patient_assignments
            ]

            if patient_ids:
                # Assign care provider to all patients in batch
                await self.patient_service.assign_care_provider_to_patients(
                    care_provider_id=care_provider_id,
                    patient_ids=patient_ids,
                    health_facility_id=health_facility_id,
                    postgres_session=postgres_session,
                )

            # Persist changes
            postgres_session.add(package)
            await postgres_session.commit()
            await postgres_session.refresh(package)

            return package

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def remove_care_provider_from_package(
        self,
        care_provider_id: str,
        package_id: str,
        health_facility_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> PackageModel:
        try:
            package = await self.fetch_package(
                package_id, detailed=True, postgres_session=postgres_session
            )
            care_provider = (
                await self.care_provider_service.fetch_care_provider(
                    care_provider_id
                )
            )
            care_provider = await postgres_session.merge(care_provider)

            # Validate care provider is assigned to the package
            if care_provider not in package.care_providers:
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="Care Provider is not part of this package.",
                )

            # Remove the care provider from the package
            package.care_providers.remove(care_provider)

            # Collect all patient IDs in the package
            patient_ids = [
                str(a.patient_id) for a in package.patient_assignments
            ]

            if patient_ids:
                # Bulk remove the care provider from all patients
                await self.patient_service.remove_care_provider_from_patients(
                    care_provider_id=care_provider_id,
                    patient_ids=patient_ids,
                    health_facility_id=health_facility_id,
                    postgres_session=postgres_session,
                )

            postgres_session.add(package)
            await postgres_session.commit()
            await postgres_session.refresh(package)

            return package

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )
