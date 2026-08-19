from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from lib.dependencies.service_dependencies import get_user_device_service
from lib.services.user_device_service import UserDeviceService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

# Legacy unprefixed /logout, kept for app builds still on the old path.
# Same behavior as POST /v1/auth/logout, which takes device_id in the body.
router = APIRouter()


@router.post("/logout", tags=["Auth"], response_model=SuccessResponse)
async def logout(
    request: Request,
    device_id: Optional[str] = None,
    user_device_service: UserDeviceService = Depends(get_user_device_service),
):
    try:
        if not device_id:
            return SuccessResponse(
                message="No device ID provided, but logged out successfully."
            )

        await user_device_service.delete_user_device(UUID(device_id))
        return SuccessResponse(message="Logged out successfully")
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to log out.",
            detail=str(e),
        )
