from functools import partial
from typing import List, Optional, Union

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from lib.core.constants import ProfileType
from lib.dependencies.service_dependencies import \
    get_care_provider_profile_service
from lib.services.care_provider_profile_service import \
    CareProviderProfileService
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.jwt import create_jwt_token
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post("/auth/email-login", response_model=SuccessResponse)
async def login_careprovider(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    care_provider_profile_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
):
    try:
        care_provider = (
            await care_provider_profile_service.authenticate_care_provider(
                email=form_data.username, password=form_data.password
            )
        )

        token = create_jwt_token(
            user_id=str(care_provider.care_provider_id),
            role=ProfileType.CARE_PROVIDER.value,
        )
        return SuccessResponse(
            message="Care provider authenticated successfully",
            data={"token": token},
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
