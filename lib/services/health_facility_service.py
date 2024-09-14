from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status
from lib.models.health_facility import HealthFacility as HealthFacilityModel
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from lib.schemas.health_facility import (
    HealthFacilityCreate,
    HealthFacilityUpdate,
)


class HealthFacilityService:
    def __init__(self, postgres_session: AsyncSession):
        self.postgres_session = postgres_session

    async def fetch_health_facility(
        self, health_facility_id: str, detailed: bool = False
    ) -> HealthFacilityModel:
        try:
            stmt = select(HealthFacilityModel).where(
                HealthFacilityModel.health_facility_id == health_facility_id
            )

            if detailed:
                stmt = stmt.options(
                    selectinload(HealthFacilityModel.care_providers),
                    selectinload(HealthFacilityModel.patients),
                )

            result = await self.postgres_session.execute(stmt)
            health_facility = result.scalars().first()

            if not health_facility:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Health facility not found.",
                )

            return health_facility

        except SQLAlchemyError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )

    async def create_health_facility(
        self, health_facility_data: HealthFacilityCreate
    ) -> HealthFacilityModel:
        try:
            new_health_facility = HealthFacilityModel(
                **health_facility_data.dict()
            )
            self.postgres_session.add(new_health_facility)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(new_health_facility)

            return new_health_facility
        except IntegrityError:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Health facility already exists.",
            )
        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database Error: {str(e)}",
            )

    async def update_health_facility(
        self, health_facility_id: str, updates: HealthFacilityUpdate
    ) -> HealthFacilityModel:
        try:
            health_facility = await self.fetch_health_facility(
                health_facility_id
            )

            for key, value in updates.dict(exclude_unset=True).items():
                setattr(health_facility, key, value)

            self.postgres_session.add(health_facility)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(health_facility)

            return health_facility

        except IntegrityError:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Health facility already exists.",
            )
        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database Error: {str(e)}",
            )

    async def delete_health_facility(self, health_facility_id: str) -> None:
        try:
            health_facility = await self.fetch_health_facility(
                health_facility_id
            )

            await self.postgres_session.delete(health_facility)
            await self.postgres_session.commit()

        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database Error: {str(e)}",
            )
