from functools import partial
from typing import List, Optional, Union

from fastapi import Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.dependencies.auth.base import get_current_user
from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import (
    get_care_provider_profile_service, get_health_facility_service)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.schemas.care_provider import CareProviderCreate
from lib.services.care_provider_profile_service import \
    CareProviderProfileService
from lib.services.health_facility_service import HealthFacilityService
from lib.utils.care_provider_permissions import CareProviderFeature
from rest_server.care_provider.profile.api_schema import CareProviderResponse
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.get("", response_model=CareProviderResponse)
async def get_care_provider_profile(
    request: Request,
    care_provider_profile_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider("read", CareProviderFeature.CARE_PROVIDER)
    ),
):
    try:
        result = await care_provider_profile_service.fetch_care_provider(
            str(current_care_provider.care_provider_id), detailed=True
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


@router.get("/health-facility", response_model=SuccessResponse)
async def get_care_provider_health_facility(
    care_provider_profile_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
    health_facility_service: HealthFacilityService = Depends(
        get_health_facility_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider("read", CareProviderFeature.CARE_PROVIDER)
    ),
):
    try:
        care_provider = (
            await care_provider_profile_service.fetch_care_provider(
                str(current_care_provider.care_provider_id)
            )
        )

        if not care_provider.health_facility_id:  # type: ignore
            raise HTTPException(
                status_code=404,
                detail="No health facility associated with the care provider.",
            )

        health_facility = await health_facility_service.fetch_health_facility(
            str(care_provider.health_facility_id),
        )
        return SuccessResponse(
            message="Health facility details fetched successfully",
            data=health_facility,
        )
    except HTTPException as e:
        raise e
    except SQLAlchemyError as e:
        response = ErrorResponse(message="Database Error", detail=str(e))
        raise HTTPException(status_code=500, detail=response.dict())
