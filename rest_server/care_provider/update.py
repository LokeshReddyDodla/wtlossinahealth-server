from typing import List, Optional, Union

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import \
    get_care_provider_profile_service
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.schemas.care_provider import CareProviderCreate, CareProviderUpdate
from lib.services.care_provider_profile_service import \
    CareProviderProfileService
from lib.utils.care_provider_permissions import CareProviderFeature
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.put("/profile", response_model=SuccessResponse)
async def update_care_provider_profile(
    request: Request,
    care_provider_id: str,
    care_provider_update: CareProviderUpdate,
    care_provider_profile_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider("update", CareProviderFeature.CARE_PROVIDER)
    ),
):
    try:
        updated_care_provider = (
            await care_provider_profile_service.update_care_provider(
                care_provider_id, care_provider_update
            )
        )

        return SuccessResponse(
            message="Care provider updated successfully.",
            data=CareProviderSchema.from_orm(updated_care_provider),
        )
    except HTTPException as e:
        raise e
    except SQLAlchemyError as e:
        response = ErrorResponse(message="Database Error", detail=str(e))
        raise HTTPException(status_code=500, detail=response.dict())


@router.put("/profile/set-password", response_model=SuccessResponse)
async def set_care_provider_password(
    raw_password: str,
    care_provider_profile_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider("update", CareProviderFeature.CARE_PROVIDER)
    ),
):
    try:

        updated_care_provider = (
            await care_provider_profile_service.set_care_provider_password(
                care_provider_id=str(current_care_provider.care_provider_id),
                raw_password=raw_password,
            )
        )

        return SuccessResponse(message="Password set successfully.")

    except HTTPException as e:
        raise e
    except IntegrityError as e:
        response = ErrorResponse(
            message="Failed to set password due to a conflict.",
            detail=str(e),
        )
        raise HTTPException(status_code=400, detail=response.dict())
    except SQLAlchemyError as e:
        response = ErrorResponse(message="Database Error", detail=str(e))
        raise HTTPException(status_code=500, detail=response.dict())
