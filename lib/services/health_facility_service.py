import re

from fastapi import status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.core.postgres_store import PostgresStore
from lib.models.health_facility import HealthFacility as HealthFacilityModel
from lib.schemas.health_facility import (
    HealthFacilityCreate,
    HealthFacilityUpdate,
)
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session


class HealthFacilityService:
    def __init__(
        self,
        postgres_store: PostgresStore,
    ):
        self.postgres_store = postgres_store

    @with_postgres_session
    async def fetch_health_facility(
        self,
        health_facility_id: str,
        detailed: bool = False,
        *,
        postgres_session: AsyncSession
    ) -> HealthFacilityModel:
        try:
            stmt = select(HealthFacilityModel).where(
                HealthFacilityModel.health_facility_id == health_facility_id
            )

            if detailed:
                stmt = stmt.options(
                    selectinload(HealthFacilityModel.care_providers),
                    selectinload(HealthFacilityModel.patients),
                    selectinload(HealthFacilityModel.packages),
                )

            result = await postgres_session.execute(stmt)
            health_facility = result.scalars().first()

            if not health_facility:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Health facility not found.",
                )

            return health_facility

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Internal Server Error",
                detail=str(e),
            )

    @with_postgres_session
    async def fetch_health_facility_by_domain(
        self,
        subdomain: str,
        custom_domain: str,
        *,
        postgres_session: AsyncSession
    ) -> HealthFacilityModel:
        try:
            stmt = select(HealthFacilityModel).where(
                (HealthFacilityModel.subdomain == subdomain)
                & (HealthFacilityModel.custom_domain == custom_domain)
            )
            result = await postgres_session.execute(stmt)
            health_facility = result.scalars().first()

            if not health_facility:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Health facility not found",
                )

            return health_facility

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def create_health_facility(
        self,
        health_facility_data: HealthFacilityCreate,
        *,
        postgres_session: AsyncSession
    ) -> HealthFacilityModel:
        try:
            if not health_facility_data.subdomain:
                health_facility_data.subdomain = self.generate_hf_subdomain(
                    health_facility_data.name
                )

            new_health_facility = HealthFacilityModel(
                **health_facility_data.model_dump()
            )
            postgres_session.add(new_health_facility)
            await postgres_session.commit()
            await postgres_session.refresh(new_health_facility)

            return new_health_facility
        except IntegrityError:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Health facility already exists.",
            )

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def update_health_facility(
        self,
        health_facility_id: str,
        updates: HealthFacilityUpdate,
        *,
        postgres_session: AsyncSession
    ) -> HealthFacilityModel:
        try:
            health_facility = await self.fetch_health_facility(
                health_facility_id, postgres_session=postgres_session
            )

            for key, value in updates.model_dump(exclude_unset=True).items():
                setattr(health_facility, key, value)

            postgres_session.add(health_facility)
            await postgres_session.commit()
            await postgres_session.refresh(health_facility)

            return health_facility

        except IntegrityError:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Health facility already exists.",
            )

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Internal Server Error",
                detail=str(e),
            )

    @with_postgres_session
    async def delete_health_facility(
        self, health_facility_id: str, *, postgres_session: AsyncSession
    ) -> None:
        try:
            health_facility = await self.fetch_health_facility(
                health_facility_id, postgres_session=postgres_session
            )

            await postgres_session.delete(health_facility)
            await postgres_session.commit()

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Internal Server Error",
                detail=str(e),
            )

    def generate_hf_subdomain(self, name: str) -> str:
        """
        Generate a sanitized subdomain from the given name.
        Replace all special characters (non-alphanumeric) with a hyphen.
        """
        sanitized_name = re.sub(
            r"[^a-zA-Z0-9]", "-", name
        )  # Replace all non-alphanumeric chars with hyphens
        sanitized_name = re.sub(
            r"-+", "-", sanitized_name
        )  # Replace multiple consecutive hyphens with a single one
        sanitized_name = sanitized_name.strip(
            "-"
        )  # Remove leading or trailing hyphens
        return sanitized_name.lower()
