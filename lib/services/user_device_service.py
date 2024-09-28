from typing import Optional
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.core.constants import ProfileType
from lib.core.types import ProfileTypeLiteral
from lib.models.user_device import UserDevice as UserDeviceModel
from lib.schemas.user_device import UserDevice, UserDeviceCreate


class UserDeviceService:
    def __init__(self, postgres_session: AsyncSession):
        self.postgres_session = postgres_session

    async def create_user_device(
        self, user_device_data: UserDeviceCreate
    ) -> UserDevice:
        """Create a new user device record in the database."""
        try:
            new_device = UserDeviceModel(**user_device_data.dict())
            self.postgres_session.add(new_device)
            await self.postgres_session.commit()
            await self.postgres_session.refresh(new_device)
            return UserDevice.from_orm(new_device)
        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            print(f"Failed to create user device: {str(e)}")
            raise

    async def get_user_devices(
        self, user_id: UUID, profile_type: str
    ) -> list[UserDevice]:
        """Retrieve all devices associated with a user."""
        try:
            stmt = select(UserDeviceModel).where(
                (UserDeviceModel.user_id == user_id)
                & (UserDeviceModel.profile_type == profile_type)
            )
            result = await self.postgres_session.execute(stmt)
            devices = result.scalars().all()
            return [UserDevice.from_orm(device) for device in devices]
        except SQLAlchemyError as e:
            print(f"Failed to retrieve user devices: {str(e)}")
            raise

    async def update_user_device(
        self, device_id: UUID, user_device_data: dict
    ) -> UserDevice:
        """Update an existing user device."""
        try:
            stmt = select(UserDeviceModel).where(
                UserDeviceModel.device_id == device_id
            )
            result = await self.postgres_session.execute(stmt)
            device = result.scalars().first()
            if not device:
                raise ValueError(f"Device with ID {device_id} not found")

            for key, value in user_device_data.items():
                setattr(device, key, value)

            await self.postgres_session.commit()
            await self.postgres_session.refresh(device)
            return UserDevice.from_orm(device)
        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            print(f"Failed to update user device: {str(e)}")
            raise

    async def delete_user_device(self, device_id: UUID):
        """Delete a user device."""
        try:
            stmt = select(UserDeviceModel).where(
                UserDeviceModel.device_id == device_id
            )
            result = await self.postgres_session.execute(stmt)
            device = result.scalars().first()
            if not device:
                raise ValueError(f"Device with ID {device_id} not found")

            await self.postgres_session.delete(device)
            await self.postgres_session.commit()
        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            print(f"Failed to delete user device: {str(e)}")
            raise

    async def create_or_update_user_device(
        self,
        user_id: UUID,
        fcm_token: str,
        profile_type: ProfileTypeLiteral,
        device_type: str,
        platform_version: Optional[str] = None,
    ) -> UserDevice:
        """Create or update a user device based on FCM token and user ID."""
        try:
            user_device_data = {
                "user_id": user_id,
                "fcm_token": fcm_token,
                "profile_type": profile_type,
                "device_type": device_type,
                "platform_version": platform_version,
            }

            if profile_type == ProfileType.PATIENT.value:
                user_device_data["patient_id"] = user_id
            elif profile_type == ProfileType.CARE_PROVIDER.value:
                user_device_data["care_provider_id"] = user_id
            else:
                raise ValueError(f"Invalid profile_type: {profile_type}")

            # Retrieve devices to check if the device already exists
            existing_devices = await self.get_user_devices(
                user_id, profile_type
            )

            for device in existing_devices:
                if device.fcm_token == fcm_token:
                    # Update the existing device if the FCM token matches
                    return await self.update_user_device(
                        device_id=device.device_id,
                        user_device_data=user_device_data,
                    )

            # If no existing device with the FCM token is found, create a new one
            return await self.create_user_device(
                UserDeviceCreate(**user_device_data)
            )
        except SQLAlchemyError as e:
            await self.postgres_session.rollback()
            print(f"Failed to create or update user device: {str(e)}")
            raise
