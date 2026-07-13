from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Path, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.database import get_postgres_session
from lib.dependencies.device_access import (
    authorize_device_access,
    resolve_profile_type,
)
from lib.dependencies.service_dependencies import get_user_device_service
from lib.models.user_device import UserDevice as UserDeviceModel
from lib.services.user_device_service import UserDeviceService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .api_schema import (
    DeleteAllDevicesResponse,
    DeleteDeviceResponse,
    DeviceHeartbeatRequest,
    ListDevicesResponse,
    UserDeviceResponse,
    UserDevicesListResponse,
)
from .router import router


@router.post(
    "/devices/heartbeat",
    response_model=SuccessResponse,
    summary="Device Heartbeat",
    description="Called on app cold boot to refresh device info (app version, FCM token, etc.).",
)
async def device_heartbeat(
    body: DeviceHeartbeatRequest,
    token_data: tuple = Depends(get_current_user),
    user_device_service: UserDeviceService = Depends(get_user_device_service),
) -> SuccessResponse:
    update_data = body.model_dump(exclude={"device_id"}, exclude_none=True)
    try:
        device = await user_device_service.update_user_device(
            device_id=UUID(body.device_id),
            user_device_data=update_data,
        )
    except ValueError:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND,
            message="Device not found",
        )
    return SuccessResponse(
        message="Heartbeat received",
        data={"device_id": str(device.device_id)},
    )


@router.get(
    "/devices",
    response_model=ListDevicesResponse,
    summary="List User Devices",
    description=(
        "Get devices for a user. "
        "If user_id is not provided, fetches devices for the authenticated user. "
        "Patients can only fetch their own devices. "
        "Care providers can fetch their own devices or their patients' devices. "
        "Admins can fetch any user's devices."
    ),
)
async def list_user_devices(
    user_id: Optional[str] = Query(
        None,
        description="User ID to fetch devices for (optional, defaults to authenticated user)",
    ),
    token_data: tuple = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
    user_device_service: UserDeviceService = Depends(get_user_device_service),
) -> ListDevicesResponse:
    try:
        current_user_id, role_value = token_data
        current_role = ProfileTypeEnum(role_value)

        # Determine target user_id (default to authenticated user if not provided)
        target_user_id = UUID(user_id) if user_id else UUID(current_user_id)

        # Resolve the profile type of the target user
        target_role = await resolve_profile_type(session, target_user_id)

        # Authorize access based on roles
        await authorize_device_access(
            session=session,
            current_user_id=UUID(current_user_id),
            current_role=current_role,
            target_user_id=target_user_id,
            target_role=target_role,
        )

        # Get all devices for the target user
        devices = await user_device_service.get_user_devices(
            user_id=target_user_id,
            profile_type=target_role.value,
        )

        device_responses = [
            UserDeviceResponse(
                device_id=str(device.device_id),
                device_type=device.device_type,
                device_name=device.device_name,
                device_model=device.device_model,
                manufacturer=device.manufacturer,
                platform_version=device.platform_version,
                app_name=device.app_name,
                app_version=device.app_version,
                is_active=device.is_active,
                created_at=device.created_at,
                last_active_at=device.last_active_at,
            )
            for device in devices
        ]

        return SuccessResponse(
            message="Devices retrieved successfully",
            data=UserDevicesListResponse(
                devices=device_responses,
                total=len(device_responses),
            ),
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Invalid user ID format",
            detail=str(e),
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to retrieve devices",
            detail=str(e),
        )


@router.delete(
    "/devices/all",
    response_model=DeleteAllDevicesResponse,
    summary="Delete All Devices",
    description=(
        "Delete all devices for a user. "
        "If user_id is not provided, deletes all devices for the authenticated user. "
        "Patients can only delete their own devices. "
        "Care providers can delete their own devices or their patients' devices. "
        "Admins can delete any user's devices."
    ),
)
async def delete_all_devices(
    user_id: Optional[str] = Query(
        None,
        description="User ID to delete devices for (optional, defaults to authenticated user)",
    ),
    token_data: tuple = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
    user_device_service: UserDeviceService = Depends(get_user_device_service),
) -> DeleteAllDevicesResponse:
    try:
        current_user_id, role_value = token_data
        current_role = ProfileTypeEnum(role_value)

        # Determine target user_id (default to authenticated user if not provided)
        target_user_id = UUID(user_id) if user_id else UUID(current_user_id)

        # Resolve the profile type of the target user
        target_role = await resolve_profile_type(session, target_user_id)

        # Authorize access based on roles
        await authorize_device_access(
            session=session,
            current_user_id=UUID(current_user_id),
            current_role=current_role,
            target_user_id=target_user_id,
            target_role=target_role,
        )

        # Delete all devices using bulk delete
        deleted_count = await user_device_service.delete_all_user_devices(
            user_id=target_user_id,
            profile_type=target_role.value,
        )

        return SuccessResponse(
            message=f"Deleted {deleted_count} device(s) successfully"
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Invalid user ID format",
            detail=str(e),
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to delete devices",
            detail=str(e),
        )


@router.delete(
    "/devices/{device_id}",
    response_model=DeleteDeviceResponse,
    summary="Delete Device",
    description=(
        "Delete a specific device by device ID. "
        "The device owner is determined automatically. "
        "Patients can only delete their own devices. "
        "Care providers can delete their own devices or their patients' devices. "
        "Admins can delete any device."
    ),
)
async def delete_device(
    device_id: str = Path(..., description="Device ID to delete"),
    token_data: tuple = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
    user_device_service: UserDeviceService = Depends(get_user_device_service),
) -> DeleteDeviceResponse:
    try:
        current_user_id, role_value = token_data
        current_role = ProfileTypeEnum(role_value)

        # Fetch the device to get its owner
        device_uuid = UUID(device_id)
        device_result = await session.execute(
            select(UserDeviceModel).where(UserDeviceModel.device_id == device_uuid)
        )
        device = device_result.scalars().first()

        if not device:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Device not found",
            )

        # Get the target user_id and profile_type from the device
        target_user_id = device.user_id
        target_profile_type = ProfileTypeEnum(device.profile_type)

        # Authorize access based on roles
        await authorize_device_access(
            session=session,
            current_user_id=UUID(current_user_id),
            current_role=current_role,
            target_user_id=target_user_id,
            target_role=target_profile_type,
        )

        # Delete the device
        await user_device_service.delete_user_device(device_uuid)

        return SuccessResponse(
            message="Device deleted successfully"
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Invalid device ID format",
            detail=str(e),
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to delete device",
            detail=str(e),
        )
