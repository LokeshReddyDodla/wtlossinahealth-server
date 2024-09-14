from functools import partial, wraps
from typing import Callable, List, Optional, Union

from fastapi import Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.future import select

from lib.dependencies.auth.base import get_current_user
from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.schemas.care_provider import CareProviderCreate
from lib.services.care_provider_service import CareProviderService
from lib.utils.care_provider_permissions import (CareProviderFeature,
                                                 CareProviderRole,
                                                 get_care_provider_permissions)
from rest_server.care_provider.profile.api_schema import CareProviderResponse
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post("", response_model=CareProviderResponse)
async def create_care_provider_profile(
    request: Request,
    care_provider: CareProviderCreate,
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider("create", CareProviderFeature.CARE_PROVIDER)
    ),
) -> Union[CareProviderResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        service = CareProviderService(session)
        try:
            new_care_provider = await service.create_care_provider(
                care_provider
            )

            return CareProviderResponse(
                message="Care Provider created successfully",
                data=CareProviderSchema.from_orm(new_care_provider),
            )
        except HTTPException as e:
            raise e
        except SQLAlchemyError as e:
            response = ErrorResponse(message="Database Error", detail=str(e))
            raise HTTPException(status_code=500, detail=response.dict())
