from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import UUID
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.models.package import Package as PackageModel
from lib.schemas.package import PackageCreate, PackageUpdate
from lib.services.care_provider_profile_service import \
    CareProviderProfileService
from lib.utils.http_exceptions import raise_http_exception


class PackageService:
    def __init__(
        self,
        postgres_session: AsyncSession,
        care_provider_service: CareProviderProfileService,
    ):
        self.postgres_session = postgres_session
        self.care_provider_service = care_provider_service

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

    async def create_package(
        self, package_data: PackageCreate, health_facility_id: UUID
    ) -> PackageModel:
        try:
            new_package = PackageModel(
                **package_data.model_dump(),
                health_facility_id=health_facility_id,
            )
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

    async def delete_package(self, package_id: str) -> None:
        try:
            package = await self.fetch_package(package_id)

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
