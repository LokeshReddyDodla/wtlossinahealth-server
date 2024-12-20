from functools import partial
from typing import List, Optional, Union

from fastapi import Depends, HTTPException, Query, Request
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
from lib.schemas.health_facility import HealthFacility as HealthFacilitySchema
from lib.schemas.patient import Patient as PatientProfileSchema
from lib.services.care_provider_profile_service import \
    CareProviderProfileService
from lib.services.health_facility_service import HealthFacilityService
from lib.utils.care_provider_permissions import (CareProviderFeature,
                                                 CareProviderPermissionAction)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.get("", response_model=SuccessResponse)
async def get_care_provider_profile(
    request: Request,
    detailed: Optional[bool] = Query(default=False),
    care_provider_profile_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ,
            CareProviderFeature.CARE_PROVIDERS,
        )
    ),
):
    try:
        result = await care_provider_profile_service.fetch_care_provider(
            str(current_care_provider.care_provider_id), detailed=detailed
        )

        return SuccessResponse(
            message="Care Provider profile retrieved successfully.",
            data=CareProviderSchema.from_orm(result),
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=500,
            message="An unexpected error occurred while fetching the care provider profile.",
            detail=str(e),
        )
