from typing import Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import exists
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from lib.core.constants import EmitMessageKey
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.models.patient_care_provider import \
    PatientCareProvider as PatientCareProviderModel
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.schemas.care_provider import CareProviderCreate, CareProviderUpdate
from lib.services.chat_service import ChatService
from lib.services.socketio_service import sio
from lib.utils.care_provider_permissions import (CareProviderRole,
                                                 get_care_provider_permissions)
from lib.utils.security import hash_password, verify_password


class CareProviderProfileService:
    def __init__(
        self, postgres_session: AsyncSession, chat_service: ChatService
    ):
        self.postgres_session = postgres_session
        self.chat_service = chat_service

    async def fetch_care_provider(
        self, care_provider_id: str, detailed: Optional[bool] = False
    ) -> CareProviderModel:
        try:
            stmt = select(CareProviderModel).where(
                CareProviderModel.care_provider_id == care_provider_id
            )

            if detailed:
                stmt = stmt.options(
                    selectinload(CareProviderModel.health_facility),
                    selectinload(
                        CareProviderModel.patient_relationships
                    ).options(
                        selectinload(PatientCareProviderModel.patient),
                        selectinload(PatientCareProviderModel.care_provider),
                    ),
                    selectinload(CareProviderModel.user_devices),
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

    async def fetch_care_provider_profiles(
        self, care_provider_ids: List[str]
    ) -> Dict[str, CareProviderSchema]:
        try:
            stmt = select(CareProviderModel).where(
                CareProviderModel.care_provider_id.in_(care_provider_ids)
            )
            result = await self.postgres_session.execute(stmt)
            profiles = result.scalars().all()

            return {
                str(profile.care_provider_id): CareProviderSchema.from_orm(
                    profile
                )
                for profile in profiles
            }
        except SQLAlchemyError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )

    async def create_care_provider(
        self, care_provider_data: CareProviderCreate
    ) -> CareProviderModel:
        try:
            # Convert role to enum and get permissions
            role_enum = CareProviderRole(care_provider_data.role.lower())
            permissions = get_care_provider_permissions(role_enum)
            care_provider_data.permissions = permissions

            new_care_provider = CareProviderModel(
                **care_provider_data.model_dump()
            )
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
    ) -> CareProviderModel:
        try:
            care_provider_profile = await self.fetch_care_provider(
                care_provider_id
            )

            for key, value in updates.model_dump(exclude_unset=True).items():
                setattr(care_provider_profile, key, value)

            updated = self._mark_profile_section_complete(
                care_provider_profile.profile_completion, "basic"
            )
            if updated:
                flag_modified(care_provider_profile, "profile_completion")

            self.postgres_session.add(care_provider_profile)

            await self.postgres_session.commit()
            await self.postgres_session.refresh(care_provider_profile)

            await self.chat_service.notify_participants(
                message_key=EmitMessageKey.CHAT_LIST_UPDATED.value,
                user_id=care_provider_id,
            )
            return care_provider_profile

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

    async def delete_care_provider(self, care_provider_id: str):
        try:
            care_provider = await self.fetch_care_provider(care_provider_id)

            await self.postgres_session.delete(care_provider)
            await self.postgres_session.commit()

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

    async def set_care_provider_password(
        self, care_provider_id: str, raw_password: str
    ) -> CareProviderModel:

        try:
            care_provider_profile = await self.fetch_care_provider(
                care_provider_id
            )

            if care_provider_profile.email is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email is required to set a password.",
                )

            hashed_password = hash_password(raw_password)

            care_provider_profile.hashed_password = hashed_password  # type: ignore
            self.postgres_session.add(care_provider_profile)

            await self.postgres_session.commit()
            await self.postgres_session.refresh(care_provider_profile)

            return care_provider_profile

        except IntegrityError:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to set password due to a database conflict.",
            )
        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )

    async def authenticate_care_provider(
        self, email: str, password: str
    ) -> CareProviderModel:
        try:
            stmt = select(CareProviderModel).where(
                CareProviderModel.email == email
            )
            result = await self.postgres_session.execute(stmt)
            care_provider = result.scalars().first()

            # Check if the care provider exists
            if not care_provider:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid email or password.",
                )

            if not care_provider.hashed_password:  # type: ignore
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Password not set. Please set your password to log in.",
                )

            # Verify the password
            if not verify_password(
                password, str(care_provider.hashed_password)
            ):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid email or password.",
                )

            return care_provider

        except SQLAlchemyError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error: {str(e)}",
            )

    def _mark_profile_section_complete(
        self, profile_completion, section: str
    ) -> bool:
        if not profile_completion[section]["is_complete"]:
            profile_completion[section]["is_complete"] = True
            return True
        return False
