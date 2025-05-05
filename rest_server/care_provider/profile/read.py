from typing import Optional

from fastapi import Depends, HTTPException, Query, Request

from lib.dependencies.auth.base import get_current_user
from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import \
    get_care_provider_profile_service
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.schemas.health_facility import HealthFacility as HealthFacilitySchema
from lib.services.care_provider_profile_service import \
    CareProviderProfileService
from lib.utils.care_provider_permissions import (CareProviderFeature,
                                                 CareProviderPermissionAction)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

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
            check_permissions=False,
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


@router.get("/code", response_model=SuccessResponse)
async def get_care_provider_profile_by_code(
    request: Request,
    code: str,
    care_provider_profile_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
    current_user=Depends(get_current_user),
):
    try:
        care_provider = await care_provider_profile_service.fetch_care_provider_by_code(
            code
        )

        return SuccessResponse(
            message="Care Provider profile retrieved successfully.",
            data={
                "profile": CareProviderSchema.from_orm(care_provider),
                "facility": HealthFacilitySchema.from_orm(
                    care_provider.health_facility
                ),
            },
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=500,
            message="An unexpected error occurred while fetching the care provider profile.",
            detail=str(e),
        )
