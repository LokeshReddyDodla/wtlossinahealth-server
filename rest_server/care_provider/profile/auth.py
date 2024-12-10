from functools import partial
from typing import List, Optional, Union

from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.core.constants import ProfileType
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import \
    get_care_provider_profile_service
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.schemas.care_provider import CareProviderCreate
from lib.services.care_provider_profile_service import \
    CareProviderProfileService
from lib.utils.care_provider_permissions import CareProviderFeature
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
    except SQLAlchemyError as e:
        response = ErrorResponse(message="Database Error", detail=str(e))
        raise HTTPException(status_code=500, detail=response.dict())
