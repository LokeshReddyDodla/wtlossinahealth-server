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

