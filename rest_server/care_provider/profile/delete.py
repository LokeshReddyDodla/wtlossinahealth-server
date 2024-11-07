from typing import List, Optional, Union

from fastapi import Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import \
    get_care_provider_profile_service
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.schemas.care_provider import CareProviderCreate
from lib.services.care_provider_profile_service import \
    CareProviderProfileService
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.delete("", response_model=SuccessResponse)
async def delete_care_provider_profile(
    request: Request,
    care_provider_id: str,
    care_provider_profile_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
):
    try:
        await care_provider_profile_service.delete_care_provider(
            care_provider_id
        )

        return SuccessResponse(message="Care provider deleted successfully.")
    except HTTPException as e:
        raise e
    except SQLAlchemyError as e:
        response = ErrorResponse(message="Database Error", detail=str(e))
        raise HTTPException(status_code=500, detail=response.dict())
