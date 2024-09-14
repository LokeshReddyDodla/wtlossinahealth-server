from sqlalchemy import exists
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.care_provider import (
    CareProvider as CareProviderSchema,
    CareProviderCreate,
    CareProviderUpdate,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from lib.services.chat_service import ChatService
from lib.utils.care_provider_permissions import (
    CareProviderRole,
    get_care_provider_permissions,
)


class CareProviderService:
    def __init__(self, postgres_session: AsyncSession):
        self.postgres_session = postgres_session
        self.chat_service = ChatService()

    async def fetch_care_provider(
        self, care_provider_id: str, detailed: bool = False
    ) -> CareProviderModel:
        try:
            stmt = select(CareProviderModel).where(
                CareProviderModel.care_provider_id == care_provider_id
            )

            if detailed:
                stmt = stmt.options(
                    selectinload(CareProviderModel.health_facility),
                    selectinload(CareProviderModel.patient_relationships),
                )

            result = await self.postgres_session.execute(stmt)
            care_provider = result.scalars().first()

            if not care_provider:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Care provider not found.",
                )

            return care_provider

        except SQLAlchemyError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )

    async def create_care_provider(
        self, care_provider_data: CareProviderCreate
    ) -> CareProviderSchema:
        try:
            # Convert role to enum and get permissions
            role_enum = CareProviderRole(care_provider_data.role.lower())
            permissions = get_care_provider_permissions(role_enum)
            care_provider_data.permissions = permissions

            new_care_provider = CareProviderModel(**care_provider_data.dict())
            self.postgres_session.add(new_care_provider)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(new_care_provider)

            return new_care_provider

        except IntegrityError:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Care provider already exists.",
            )
        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )

    async def update_care_provider(
        self, care_provider_id: str, updates: CareProviderUpdate
    ) -> CareProviderSchema:
        try:
            care_provider = await self.fetch_care_provider(care_provider_id)
            care_provider_schema = CareProviderSchema.from_orm(care_provider)

            old_first_name = care_provider_schema.first_name
            old_last_name = care_provider_schema.last_name

            for key, value in updates.dict(exclude_unset=True).items():
                setattr(care_provider, key, value)

            self.postgres_session.add(care_provider)

            if (
                old_first_name != updates.first_name
                or old_last_name != updates.last_name
            ):
                await self.chat_service.update_participant_name(
                    participant_id=str(care_provider.care_provider_id),
                    new_name=f"{care_provider.first_name} {care_provider.last_name}",
                    participant_type="care_provider",
                )

            await self.postgres_session.commit()
            await self.postgres_session.refresh(care_provider)

            return care_provider

        except IntegrityError:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Care provider already exists.",
            )
        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )

    async def delete_care_provider(self, care_provider_id: str) -> str:
        try:
            care_provider = await self.fetch_care_provider(care_provider_id)
            await self.postgres_session.delete(care_provider)
            await self.postgres_session.commit()

            return "Care provider deleted successfully."

        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database Error: {str(e)}",
            )

    async def check_care_provider_exists(self, care_provider_id: str) -> bool:
        try:
            stmt = select(
                exists().where(
                    CareProviderModel.care_provider_id == care_provider_id
                )
            )
            result = await self.postgres_session.execute(stmt)
            (exists_result,) = result.scalars()

            if not exists_result:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Care Provider not found.",
                )

            return True
        except SQLAlchemyError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )
