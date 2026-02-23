from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import delete, desc, func
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
    async def get_user_last_active_at(
        self,
        user_id: UUID,
        profile_type: Optional[str] = None,
        *,
        postgres_session: AsyncSession,
    ) -> Optional[datetime]:
        try:
            stmt = select(func.max(UserDeviceModel.last_active_at)).where(
                UserDeviceModel.user_id == user_id
            )
            if profile_type:
                stmt = stmt.where(UserDeviceModel.profile_type == profile_type)

            result = await postgres_session.execute(stmt)
            return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            print(f"Failed to fetch last_active_at: {str(e)}")
            raise

    @with_postgres_session
    async def get_last_active_map(
        self,
        user_ids: list[str],
        profile_type: str,
        *,
        postgres_session: AsyncSession,
    ) -> dict[str, datetime]:
        try:
            stmt = (
                select(
                    UserDeviceModel.user_id,
                    func.max(UserDeviceModel.last_active_at),
                )
                .where(
                    UserDeviceModel.user_id.in_(user_ids),
                    UserDeviceModel.profile_type == profile_type,
                )
                .group_by(UserDeviceModel.user_id)
            )
            rows = await postgres_session.execute(stmt)

            return {
                str(user_id): last_active
                for user_id, last_active in rows.all()
            }

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            print(f"Failed to fetch last active map: {str(e)}")
            raise

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
            stmt = select(UserDeviceModel).where(
                UserDeviceModel.user_id == user_id,
            )
            if profile_type is not None:
                stmt = stmt.where(UserDeviceModel.profile_type == profile_type)

            stmt = stmt.order_by(
                desc(UserDeviceModel.last_active_at).nullslast()
            )

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
    async def delete_all_user_devices(
        self,
        user_id: UUID,
        profile_type: Optional[str] = None,
        *,
        postgres_session: AsyncSession,
    ) -> int:
        try:
            delete_stmt = delete(UserDeviceModel).where(
                UserDeviceModel.user_id == user_id
            )
            if profile_type:
                delete_stmt = delete_stmt.where(
                    UserDeviceModel.profile_type == profile_type
                )

            result = await postgres_session.execute(delete_stmt)
            await postgres_session.commit()
            return result.rowcount
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            print(f"Failed to delete user devices: {str(e)}")
            raise

    @with_postgres_session
    async def create_or_update_user_device(
        self,
        user_id: UUID,
        profile_type: ProfileTypeLiteral,
        fcm_token: Optional[str] = None,
        device_type: Optional[str] = None,
        platform_version: Optional[str] = None,
        device_model: Optional[str] = None,
        manufacturer: Optional[str] = None,
        device_name: Optional[str] = None,
        is_physical_device: Optional[bool] = None,
        app_name: Optional[str] = None,
        app_version: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        location_name: Optional[str] = None,
        *,
        postgres_session: AsyncSession,
    ) -> UserDeviceModel:
        try:
            user_device_data = {
                "user_id": user_id,
                "fcm_token": fcm_token,
                "profile_type": profile_type,
                "device_type": device_type,
                "platform_version": platform_version,
                "device_model": device_model,
                "manufacturer": manufacturer,
                "device_name": device_name,
                "is_physical_device": is_physical_device,
                "app_name": app_name,
                "app_version": app_version,
                "latitude": latitude,
                "longitude": longitude,
                "location_name": location_name,
            }

            # Retrieve devices to check if the device already exists
            existing_devices = await self.get_user_devices(
                user_id, profile_type, postgres_session=postgres_session
            )

            for device in existing_devices:
                # Prefer FCM match if provided
                if fcm_token and device.fcm_token == fcm_token:
                    return await self.update_user_device(
                        device_id=device.device_id,
                        user_device_data=user_device_data,
                        postgres_session=postgres_session,
                    )
                # Fallback to match on device_name + type
                elif (
                    not fcm_token
                    and device.device_name == device_name
                    and device.device_type == device_type
                ):
                    return await self.update_user_device(
                        device_id=device.device_id,
                        user_device_data=user_device_data,
                        postgres_session=postgres_session,
                    )

            # If no existing device with the FCM token is found, create a new one
            return await self.create_user_device(
                UserDeviceCreate(**user_device_data),
                postgres_session=postgres_session,
            )
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            print(f"Failed to create or update user device: {str(e)}")
            raise
