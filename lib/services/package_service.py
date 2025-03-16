import random
import string
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import UUID
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from lib.models.package import Package as PackageModel
from lib.models.patient import Patient as PatientModel
from lib.schemas.package import PackageCreate, PackageUpdate
from lib.services.care_provider_profile_service import \
    CareProviderProfileService
from lib.services.chat.chat_management_service import ChatManagementService
from lib.services.chat.chat_notification_service import ChatNotificationService
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.http_exceptions import raise_http_exception


class PackageService:
    def __init__(
        self,
        postgres_session: AsyncSession,
        patient_service: PatientProfileService,
        care_provider_service: CareProviderProfileService,
        chat_notification_service: ChatNotificationService,
        chat_management_service: ChatManagementService,
    ):
        self.postgres_session = postgres_session
        self.patient_service = patient_service
        self.care_provider_service = care_provider_service
        self.chat_notification_service = chat_notification_service
        self.chat_management_service = chat_management_service

    async def generate_unique_code(self) -> str:
        while True:
            code = "".join(
                random.choices(string.ascii_uppercase + string.digits, k=6)
            )
            stmt = select(PackageModel).where(PackageModel.code == code)
            result = await self.postgres_session.execute(stmt)
            if not result.scalars().first():
                return code

    async def fetch_package(
        self, package_id: str, detailed: Optional[bool] = False
    ) -> PackageModel:
        try:
            stmt = select(PackageModel).where(
                PackageModel.package_id == package_id
            )

            if detailed:
                stmt = stmt.options(
                    selectinload(PackageModel.health_facility),
                    selectinload(PackageModel.care_providers),
                    selectinload(PackageModel.patients),
                )

            result = await self.postgres_session.execute(stmt)
            package = result.scalars().first()

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

    async def fetch_package_by_code(
        self, package_code: str, detailed: Optional[bool] = False
    ) -> PackageModel:
        try:
            stmt = select(PackageModel).where(
                PackageModel.code == package_code
            )

            if detailed:
                stmt = stmt.options(
                    selectinload(PackageModel.health_facility),
                    selectinload(PackageModel.care_providers),
                    selectinload(PackageModel.patients),
                )

            result = await self.postgres_session.execute(stmt)
            package = result.scalars().first()

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

    async def fetch_packages_in_health_facility(
        self, health_facility_id: str
    ) -> List[PackageModel]:
        try:
            stmt = (
                select(PackageModel)
                .where(PackageModel.health_facility_id == health_facility_id)
                .options(
                    selectinload(PackageModel.care_providers),
                    selectinload(PackageModel.patients),
                )
            )

            result = await self.postgres_session.execute(stmt)
            packages = result.scalars().all()

            return list(packages)

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    async def create_package(
        self,
        package_data: PackageCreate,
        health_facility_id: UUID,
        created_by_id: UUID,
    ) -> PackageModel:
        try:
            care_provider = (
                await self.care_provider_service.fetch_care_provider(
                    str(created_by_id)
                )
            )
            care_provider = await self.postgres_session.merge(care_provider)

            code = await self.generate_unique_code()
            new_package = PackageModel(
                **package_data.model_dump(),
                code=code,
                health_facility_id=health_facility_id,
                created_by=care_provider,
            )
            new_package.care_providers.append(care_provider)

            self.postgres_session.add(new_package)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(new_package)

            return new_package

        except IntegrityError as e:
            await self.postgres_session.rollback()
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
            await self.postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    async def update_package(
        self, package_id: str, updates: PackageUpdate
    ) -> PackageModel:
        try:
            package = await self.fetch_package(package_id)

            for key, value in updates.model_dump(exclude_unset=True).items():
                setattr(package, key, value)

            self.postgres_session.add(package)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(package)

            return package

        except IntegrityError:
            await self.postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Package already exists.",
            )

        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    async def delete_package(
        self, package_id: str, health_facility_id: str
    ) -> None:
        try:
            package = await self.fetch_package(package_id)

            if str(package.health_facility_id) != health_facility_id:
                raise_http_exception(
                    status_code=status.HTTP_403_FORBIDDEN,
                    message="You do not have permission to delete this package as it belongs to a different health facility.",
                )

            await self.postgres_session.delete(package)
            await self.postgres_session.commit()

        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    async def assign_care_provider_to_package(
        self,
        package_id: str,
        care_provider_id: str,
    ) -> PackageModel:
        try:
            package = await self.fetch_package(package_id, detailed=True)
            care_provider = (
                await self.care_provider_service.fetch_care_provider(
                    care_provider_id
                )
            )

            # Ensure the care provider and package belong to the same health facility
            if package.health_facility_id != care_provider.health_facility_id:  # type: ignore
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="Care Provider and Package belong to different health facilities.",
                )

            # Assign the care provider to the package
            if care_provider not in package.care_providers:
                package.care_providers.append(care_provider)
                self.postgres_session.add(package)
                await self.postgres_session.commit()
                await self.postgres_session.refresh(package)

            return package

        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    async def assign_patient_to_package(
        self, patient_id: str, package_id: str
    ) -> PackageModel:
        try:
            package = await self.fetch_package(package_id, detailed=True)
            patient = await self.patient_service.fetch_patient_profile(
                patient_id
            )

            # Check if the patient is already part of the package
            if patient in package.patients:
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="Patient is already part of this package.",
                )

            # Check if the patient is already in another package
            if patient.package:
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=(
                        f"Patient is already part of the package '{patient.package.name}'. "
                        "Please remove them from the current package before reassigning."
                    ),
                )

            # Assign the patient to the package
            package.patients.append(patient)
            patient.package = package

            self.postgres_session.add(package)
            self.postgres_session.add(patient)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(package)
            await self.postgres_session.refresh(patient)

            # Handle care provider chat connections
            await self._handle_package_care_provider_chats(patient, package)

            return package

        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    async def patient_join_package_by_code(
        self, patient_id: str, package_code: str
    ) -> PackageModel:

        try:
            package = await self.fetch_package_by_code(
                package_code, detailed=True
            )
            patient = await self.patient_service.fetch_patient_profile(
                patient_id
            )

            # Check if the patient is already part of the package
            if patient in package.patients:
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="Patient is already part of this package.",
                )

            # Check if the patient is already in another package
            if patient.package:
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=(
                        f"Patient is already part of the package '{patient.package.name}'. "
                        "Please remove them from the current package before reassigning."
                    ),
                )

            # Assign the patient to the package
            package.patients.append(patient)
            patient.package = package

            self.postgres_session.add(package)
            self.postgres_session.add(patient)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(package)
            await self.postgres_session.refresh(patient)

            # Handle care provider chat connections
            await self._handle_package_care_provider_chats(patient, package)

            return package

        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    async def remove_care_provider_from_package(
        self, care_provider_id: str, package_id: str
    ) -> PackageModel:
        try:
            package = await self.fetch_package(package_id, detailed=True)
            care_provider = (
                await self.care_provider_service.fetch_care_provider(
                    care_provider_id
                )
            )

            # Check if the care provider is part of the package
            if care_provider not in package.care_providers:
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="Care Provider is not part of this package.",
                )

            # Remove the care provider from the package
            package.care_providers.remove(care_provider)

            self.postgres_session.add(package)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(package)

            return package

        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    async def remove_patient_from_package(
        self, patient_id: str, package_id: str
    ) -> PackageModel:
        try:
            package = await self.fetch_package(package_id, detailed=True)
            patient = await self.patient_service.fetch_patient_profile(
                patient_id
            )

            # Check if the patient is part of the package
            if patient not in package.patients:
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="Patient is not part of this package.",
                )

            package.patients.remove(patient)
            patient.package = None

            self.postgres_session.add(package)
            self.postgres_session.add(patient)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(package)
            await self.postgres_session.refresh(patient)

            return package

        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    async def _handle_package_care_provider_chats(
        self, patient: PatientModel, package: PackageModel
    ):
        # Loop through all care providers in the package
        for care_provider in package.care_providers:
            # Create a direct chat between the patient and care provider
            await self.chat_management_service.create_direct_and_group_chats(
                patient=patient, care_provider=care_provider
            )
