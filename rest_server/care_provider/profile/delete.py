from typing import List, Optional, Union

from fastapi import Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.future import select

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.schemas.care_provider import CareProviderCreate
from lib.services.care_provider_service import CareProviderService
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.delete("/{care_provider_id}", response_model=SuccessResponse)
async def delete_care_provider_profile(
    request: Request, care_provider_id: str
) -> Union[SuccessResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        service = CareProviderService(session)
        try:
            await service.delete_care_provider(care_provider_id)

            return SuccessResponse(
                message="Care provider deleted successfully."
            )
        except HTTPException as e:
            raise e
        except SQLAlchemyError as e:
            response = ErrorResponse(message="Database Error", detail=str(e))
            raise HTTPException(status_code=500, detail=response.dict())
