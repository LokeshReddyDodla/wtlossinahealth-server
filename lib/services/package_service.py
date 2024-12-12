from fastapi import HTTPException, status
from sqlalchemy import UUID
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.models.package import Package as PackageModel
from lib.schemas.package import PackageCreate, PackageUpdate
from lib.utils.http_exceptions import raise_http_exception


class PackageService:
    def __init__(self, postgres_session: AsyncSession):
        self.postgres_session = postgres_session

    async def fetch_package(self, package_id: str) -> PackageModel:
        try:
            stmt = select(PackageModel).where(
                PackageModel.package_id == package_id
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
