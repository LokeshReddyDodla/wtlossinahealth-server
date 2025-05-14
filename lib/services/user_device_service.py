from typing import Optional
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.core.constants import ProfileTypeEnum
from lib.core.postgres_store import PostgresStore
from lib.core.types import ProfileTypeLiteral
from lib.models.user_device import UserDevice as UserDeviceModel
from lib.schemas.user_device import UserDeviceCreate
from lib.utils.postgres_session_decorator import with_postgres_session


class UserDeviceService:
    def __init__(
        self,
        postgres_store: PostgresStore,
    ):
        self.postgres_store = postgres_store

    @with_postgres_session
    async def create_user_device(
        self,
        user_device_data: UserDeviceCreate,
        *,
        postgres_session: AsyncSession,
    ) -> UserDeviceModel:
        """Create a new user device record in the database."""
        try:
            new_device = UserDeviceModel(**user_device_data.dict())
            postgres_session.add(new_device)
            await postgres_session.commit()
            await postgres_session.refresh(new_device)
            return new_device
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            print(f"Failed to create user device: {str(e)}")
            raise

    @with_postgres_session
    async def get_user_devices(
        self,
        user_id: UUID,
        profile_type: Optional[str] = None,
        *,
        postgres_session: AsyncSession,
    ) -> list[UserDeviceModel]:
        """Retrieve all devices associated with a user."""
        try:
            stmt = (
                select(UserDeviceModel)
                .where(UserDeviceModel.user_id == user_id)
                .options(
                    selectinload(UserDeviceModel.patient),
                    selectinload(UserDeviceModel.care_provider),
                )
            )
            if profile_type is not None:
                stmt = stmt.where(UserDeviceModel.profile_type == profile_type)

            result = await postgres_session.execute(stmt)
            devices = result.scalars().all()
            return list(devices)
        except SQLAlchemyError as e:
            print(f"Failed to retrieve user devices: {str(e)}")
            raise

    @with_postgres_session
    async def update_user_device(
        self,
        device_id: UUID,
        user_device_data: dict,
        *,
        postgres_session: AsyncSession,
    ) -> UserDeviceModel:
        """Update an existing user device."""
        try:
            stmt = select(UserDeviceModel).where(
                UserDeviceModel.device_id == device_id
            )
            result = await postgres_session.execute(stmt)
            device = result.scalars().first()
            if not device:
                raise ValueError(f"Device with ID {device_id} not found")

            for key, value in user_device_data.items():
                setattr(device, key, value)

            await postgres_session.commit()
            await postgres_session.refresh(device)
            return device
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            print(f"Failed to update user device: {str(e)}")
            raise

    @with_postgres_session
    async def delete_user_device(
        self, device_id: UUID, *, postgres_session: AsyncSession
    ):
        """Delete a user device."""
        try:
            stmt = select(UserDeviceModel).where(
                UserDeviceModel.device_id == device_id
            )
            result = await postgres_session.execute(stmt)
            device = result.scalars().first()
            if not device:
                # raise ValueError(f"Device with ID {device_id} not found")
                return

            await postgres_session.delete(device)
            await postgres_session.commit()
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            print(f"Failed to delete user device: {str(e)}")
            raise

    @with_postgres_session
    async def create_or_update_user_device(
        self,
        user_id: UUID,
        fcm_token: str,
        profile_type: ProfileTypeLiteral,
        device_type: str,
        platform_version: Optional[str] = None,
        *,
        postgres_session: AsyncSession,
    ) -> UserDeviceModel:
        """Create or update a user device based on FCM token and user ID."""
        try:
            user_device_data = {
                "user_id": user_id,
                "fcm_token": fcm_token,
                "profile_type": profile_type,
                "device_type": device_type,
                "platform_version": platform_version,
            }

            if profile_type == ProfileTypeEnum.PATIENT.value:
                user_device_data["patient_id"] = user_id
            elif profile_type == ProfileTypeEnum.CARE_PROVIDER.value:
                user_device_data["care_provider_id"] = user_id
            else:
                raise ValueError(f"Invalid profile_type: {profile_type}")

            # Retrieve devices to check if the device already exists
            existing_devices = await self.get_user_devices(
                user_id, profile_type
            )

            for device in existing_devices:
                if device.fcm_token == fcm_token:  # type: ignore
                    # Update the existing device if the FCM token matches
                    return await self.update_user_device(
                        device_id=device.device_id,  # type: ignore
                        user_device_data=user_device_data,
                    )

            # If no existing device with the FCM token is found, create a new one
            return await self.create_user_device(
                UserDeviceCreate(**user_device_data)
            )
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            print(f"Failed to create or update user device: {str(e)}")
            raise
