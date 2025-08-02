from typing import Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.service_dependencies import (
    get_care_provider_profile_service,
    get_user_device_service,
)
from lib.services.care_provider_profile_service import (
    CareProviderProfileService,
)
from lib.services.user_device_service import UserDeviceService
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.jwt import create_jwt_token
from rest_server.response_models import SuccessResponse

from .router import router


class CareProviderLoginData(BaseModel):
    email: str
    password: str
    fcm_token: Optional[str] = None
    device_type: Optional[str] = None
    platform_version: Optional[str] = None


@router.post("/auth/email-login", response_model=SuccessResponse)
async def login_careprovider(
    request: Request,
    login_data: CareProviderLoginData,
    user_device_service: UserDeviceService = Depends(get_user_device_service),
    care_provider_profile_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
):
    try:
        care_provider = (
            await care_provider_profile_service.authenticate_care_provider(
                email=login_data.email, password=login_data.password
            )
        )  # type: ignore

        token = create_jwt_token(
            user_id=str(care_provider.care_provider_id),
            role=ProfileTypeEnum.CARE_PROVIDER.value,
        )

        device = None
        if login_data.fcm_token:
            device = await user_device_service.create_or_update_user_device(
                user_id=care_provider.care_provider_id,
                fcm_token=login_data.fcm_token,
                device_type=login_data.device_type,
                profile_type=ProfileTypeEnum.CARE_PROVIDER.value,
                platform_version=login_data.platform_version,
            )  # type: ignore

        return SuccessResponse(
            message="Care provider authenticated successfully",
            data={
                "token": token,
                "user_id": str(care_provider.care_provider_id),
                "device_id": str(device.device_id) if device else None,
            },
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
