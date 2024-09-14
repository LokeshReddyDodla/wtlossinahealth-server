from lib.models.care_provider import CareProvider as CareProviderModel
from fastapi import HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient
from sqlalchemy.exc import SQLAlchemyError

from typing import List, Optional, Union
from sqlalchemy.future import select
from lib.schemas.care_provider import (
    CareProvider as CareProviderSchema,
    CareProviderCreate,
)
from sqlalchemy.exc import IntegrityError
from lib.services.care_provider_service import CareProviderService
from rest_server.response_models import SuccessResponse, ErrorResponse
from .router import router


@router.delete("/{care_provider_id}", response_model=SuccessResponse)
async def delete_care_provider(
    request: Request, care_provider_id: str
) -> Union[SuccessResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        service = CareProviderService(session)
        message = await service.delete_care_provider(care_provider_id)

        return SuccessResponse(message=message)
