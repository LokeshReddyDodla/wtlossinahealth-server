from lib.models.care_provider import CareProvider as CareProviderModel
from fastapi import HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient
from sqlalchemy.exc import SQLAlchemyError

from typing import List, Optional, Union
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from lib.schemas.care_provider import (
    CareProvider as CareProviderSchema,
    CareProviderCreate,
)
from sqlalchemy.exc import IntegrityError
from rest_server.care_provider.api_schema import CareProviderResponse
from rest_server.response_models import SuccessResponse, ErrorResponse
from .router import router


@router.get("/{care_provider_id}", response_model=CareProviderResponse)
async def get_care_provider(
    request: Request, care_provider_id: str
) -> Union[CareProviderResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            result = await session.execute(
                select(CareProviderModel)
                .where(CareProviderModel.care_provider_id == care_provider_id)
                .options(
                    selectinload(CareProviderModel.health_facility),
                    selectinload(CareProviderModel.patient_relationships),
                )
            )
            care_provider = result.scalars().first()

            if not care_provider:
                raise HTTPException(
                    status_code=404, detail="Care provider not found."
                )

            return CareProviderResponse(
                message="Care Provider created successfully",
                data=CareProviderSchema.from_orm(care_provider),
            )
        except SQLAlchemyError as e:
            response = ErrorResponse(message="Database Error", detail=str(e))
            raise HTTPException(status_code=500, detail=response.dict())
