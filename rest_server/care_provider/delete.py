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
from rest_server.response_models import SuccessResponse, ErrorResponse
from .router import router


@router.delete("/{care_provider_id}", response_model=SuccessResponse)
async def delete_care_provider(
    request: Request, care_provider_id: str
) -> Union[SuccessResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            result = await session.execute(
                select(CareProviderModel).where(
                    CareProviderModel.care_provider_id == care_provider_id
                )
            )
            care_provider = result.scalars().first()

            if not care_provider:
                raise HTTPException(
                    status_code=404, detail="Care provider not found."
                )

            await session.delete(care_provider)
            await session.commit()

            return SuccessResponse(
                message="Care provider deleted successfully."
            )
        except SQLAlchemyError as e:
            response = ErrorResponse(message="Database Error", detail=str(e))
            raise HTTPException(status_code=500, detail=response.dict())
