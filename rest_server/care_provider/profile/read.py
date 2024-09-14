from functools import partial
from typing import List, Optional, Union

from fastapi import Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.dependencies.auth.base import get_current_user
from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.schemas.care_provider import CareProviderCreate
from lib.services.care_provider_service import CareProviderService
from lib.utils.care_provider_permissions import CareProviderFeature
from rest_server.care_provider.profile.api_schema import CareProviderResponse
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.get("", response_model=CareProviderResponse)
async def get_care_provider_profile(
    request: Request,
    care_provider_id: str,
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider("read", CareProviderFeature.CARE_PROVIDER)
    ),
) -> Union[CareProviderResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        service = CareProviderService(session)
        try:
            result = await service.fetch_care_provider(
                care_provider_id, detailed=True
            )

            return CareProviderResponse(
                message="Care Provider created successfully",
                data=CareProviderSchema.from_orm(result),
            )
        except HTTPException as e:
            raise e
        except SQLAlchemyError as e:
            response = ErrorResponse(message="Database Error", detail=str(e))
            raise HTTPException(status_code=500, detail=response.dict())
