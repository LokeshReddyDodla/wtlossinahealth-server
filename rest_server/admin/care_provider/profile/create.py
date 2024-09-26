from typing import Callable, List, Optional, Union

from fastapi import Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.dependencies.auth.admin_auth import get_current_admin
from lib.dependencies.database import get_postgres_session
from lib.models.admin import Admin
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.schemas.care_provider import CareProviderCreate
from lib.services.care_provider_service import CareProviderService
from rest_server.care_provider.profile.api_schema import CareProviderResponse
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post("", response_model=CareProviderResponse)
async def create_care_provider_profile(
    request: Request,
    care_provider: CareProviderCreate,
    session: AsyncSession = Depends(get_postgres_session),
    current_admin: Admin = Depends(get_current_admin),
) -> Union[CareProviderResponse, HTTPException]:

    service = CareProviderService(session)
    try:
        new_care_provider = await service.create_care_provider(care_provider)

        return CareProviderResponse(
            message="Care Provider created successfully",
            data=CareProviderSchema.from_orm(new_care_provider),
        )
    except HTTPException as e:
        raise e
    except SQLAlchemyError as e:
        response = ErrorResponse(message="Database Error", detail=str(e))
        raise HTTPException(status_code=500, detail=response.dict())
