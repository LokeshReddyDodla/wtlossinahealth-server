from uuid import UUID

from fastapi import Depends, HTTPException, Path, Request, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.service_dependencies import get_user_device_service
from lib.services.user_device_service import UserDeviceService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .api_schema import (
    DeleteAllDevicesResponse,
    DeleteDeviceResponse,
    ListDevicesResponse,
    UserDeviceResponse,
    UserDevicesListResponse,
)
from .router import router


@router.get(
    "/devices",
    response_model=ListDevicesResponse,
    summary="List User Devices",
    description="Get all logged-in devices for the authenticated user",
)
async def list_user_devices(
    request: Request,
    token_data: tuple = Depends(get_current_user),
    user_device_service: UserDeviceService = Depends(get_user_device_service),
) -> ListDevicesResponse:
    try:
        user_id, role_value = token_data
        role = ProfileTypeEnum(role_value)

        # Get all devices for the user
        devices = await user_device_service.get_user_devices(
            user_id=UUID(user_id),
            profile_type=role.value,
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
                last_active_at=device.last_active_at,
                created_at=device.last_updated_at,
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
    "/devices/{device_id}",
    response_model=DeleteDeviceResponse,
    summary="Delete Device",
    description="Delete a specific device by device ID for the authenticated user",
)
async def delete_device(
    device_id: str = Path(..., description="Device ID to delete"),
    token_data: tuple = Depends(get_current_user),
    user_device_service: UserDeviceService = Depends(get_user_device_service),
) -> DeleteDeviceResponse:
    try:
        user_id, role_value = token_data
        role = ProfileTypeEnum(role_value)

        # Get all devices for the user to verify ownership
        devices = await user_device_service.get_user_devices(
            user_id=UUID(user_id),
            profile_type=role.value,
        )

        # Check if the device belongs to the user
        device_to_delete = None
        for device in devices:
            if str(device.device_id) == device_id:
                device_to_delete = device
                break

        if not device_to_delete:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Device not found",
                detail="The specified device does not belong to the authenticated user.",
            )

        # Delete the device
        await user_device_service.delete_user_device(device_to_delete.device_id)

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


@router.delete(
    "/devices/all",
    response_model=DeleteAllDevicesResponse,
    summary="Delete All Devices",
    description="Delete all devices for the authenticated user",
)
async def delete_all_devices(
    request: Request,
    token_data: tuple = Depends(get_current_user),
    user_device_service: UserDeviceService = Depends(get_user_device_service),
) -> DeleteAllDevicesResponse:
    try:
        user_id, role_value = token_data
        role = ProfileTypeEnum(role_value)

        # Get all devices for the user
        devices = await user_device_service.get_user_devices(
            user_id=UUID(user_id),
            profile_type=role.value,
        )

        # Delete all devices
        deleted_count = 0
        for device in devices:
            try:
                await user_device_service.delete_user_device(device.device_id)
                deleted_count += 1
            except Exception:
                # Continue deleting other devices even if one fails
                pass

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
