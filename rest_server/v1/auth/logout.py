from uuid import UUID

from fastapi import Depends, HTTPException, Request, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.service_dependencies import get_user_device_service
from lib.services.user_device_service import UserDeviceService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .api_schema import LogoutAllResponse, LogoutRequest, LogoutResponse
from .router import router


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Logout",
    description="Logout user by removing device information",
)
async def logout(
    request: Request,
    logout_request: LogoutRequest,
    user_device_service: UserDeviceService = Depends(get_user_device_service),
) -> LogoutResponse:
    try:
        if not logout_request.device_id:
            return SuccessResponse(
                message="No device ID provided, but logged out successfully."
            )

        await user_device_service.delete_user_device(
            UUID(logout_request.device_id)
        )
        
        return SuccessResponse(
            message="Logged out successfully"
        )
        
    except ValueError as e:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Invalid device ID format",
            detail=str(e),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to log out",
            detail=str(e),
        )


@router.post(
    "/logout-all",
    response_model=LogoutAllResponse,
    summary="Logout All Devices",
    description="Logout user from all devices by removing all device information",
)
async def logout_all_devices(
    request: Request,
    token_data: tuple = Depends(get_current_user),
    user_device_service: UserDeviceService = Depends(get_user_device_service),
) -> LogoutAllResponse:
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
            message=f"Logged out from {deleted_count} device(s) successfully"
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
            message="Failed to log out from all devices",
            detail=str(e),
        )
