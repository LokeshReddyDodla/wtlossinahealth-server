from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.models.care_provider import CareProvider as CareProviderModel
from fastapi import HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient
from sqlalchemy.exc import SQLAlchemyError

from typing import List, Optional, Union
from sqlalchemy.future import select
from lib.schemas.care_provider import (
    CareProvider as CareProviderSchema,
    CareProviderCreate,
    CareProviderUpdate,
)
from sqlalchemy.exc import IntegrityError
from lib.utils.care_provider_permissions import CareProviderFeature
from rest_server.care_provider.api_schema import CareProviderResponse
from rest_server.response_models import SuccessResponse, ErrorResponse
from .router import router


@router.put("", response_model=CareProviderResponse)
async def update_care_provider(
    request: Request,
    care_provider_id: str,
    care_provider_update: CareProviderUpdate,
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider("update", CareProviderFeature.CARE_PROVIDER)
    ),
) -> Union[CareProviderResponse, HTTPException]:
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

            for key, value in care_provider_update.dict(
                exclude_unset=True
            ).items():
                setattr(care_provider, key, value)

            session.add(care_provider)
            await session.commit()
            await session.refresh(care_provider)

            return CareProviderResponse(
                message="Care Provider created successfully",
                data=CareProviderSchema.from_orm(care_provider),
            )
        except IntegrityError:
            raise HTTPException(
                status_code=400, detail="Care provider already exists."
            )
        except SQLAlchemyError as e:
            response = ErrorResponse(message="Database Error", detail=str(e))
            raise HTTPException(status_code=500, detail=response.dict())
