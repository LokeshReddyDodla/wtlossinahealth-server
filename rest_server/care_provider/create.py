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
from rest_server.care_provider.api_schema import CareProviderResponse
from rest_server.response_models import SuccessResponse, ErrorResponse
from .router import router


@router.post("", response_model=CareProviderResponse)
async def create_care_provider(
    request: Request, care_provider: CareProviderCreate
) -> Union[CareProviderResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            new_care_provider = CareProviderModel(**care_provider.dict())
            session.add(new_care_provider)
            await session.commit()
            await session.refresh(new_care_provider)

            return CareProviderResponse(
                message="Care Provider created successfully",
                data=CareProviderSchema.from_orm(new_care_provider),
            )
        except IntegrityError:
            raise HTTPException(
                status_code=400, detail="Care provider already exists."
            )
        except SQLAlchemyError as e:
            response = ErrorResponse(message="Database Error", detail=str(e))
            raise HTTPException(status_code=500, detail=response.dict())
