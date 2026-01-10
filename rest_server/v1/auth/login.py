from fastapi import Depends, HTTPException, Request, status

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

from .api_schema import (
    AuthTokenResponse,
    CareProviderLoginRequest,
    CareProviderLoginResponse,
)
from .router import router


@router.post(
    "/care-provider/email-login",
    response_model=CareProviderLoginResponse,
    summary="Care Provider Email Login",
    description="Authenticate care provider using email and password",
)
async def login_care_provider(
    request: Request,
    login_request: CareProviderLoginRequest,
    user_device_service: UserDeviceService = Depends(get_user_device_service),
    care_provider_profile_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
) -> CareProviderLoginResponse:
    try:
        # Authenticate care provider
        care_provider = (
            await care_provider_profile_service.authenticate_care_provider(
                email=login_request.email,
                password=login_request.password
            )
        )

        # Generate JWT token
        token = create_jwt_token(
            user_id=str(care_provider.care_provider_id),
            role=ProfileTypeEnum.CARE_PROVIDER.value,
        )

        # Store or update user device information
        device = await user_device_service.create_or_update_user_device(
            user_id=care_provider.care_provider_id,
            fcm_token=login_request.fcm_token,
            device_type=login_request.device_type,
            profile_type=ProfileTypeEnum.CARE_PROVIDER.value,
            platform_version=login_request.platform_version,
        )

        return SuccessResponse(
            message="Care provider authenticated successfully",
            data=AuthTokenResponse(
                token=token,
                user_id=str(care_provider.care_provider_id),
                device_id=str(device.device_id) if device else None,
            ),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal server error",
            detail=str(e),
        )
