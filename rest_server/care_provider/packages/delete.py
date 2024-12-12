from fastapi import Depends, HTTPException, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import get_package_service
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.schemas.health_facility import HealthFacility as HealthFacilitySchema
from lib.schemas.package import Package as PackageSchema
from lib.services.care_provider_profile_service import \
    CareProviderProfileService
from lib.services.package_service import PackageService
from lib.utils.care_provider_permissions import (CareProviderFeature,
                                                 CareProviderPermissionAction)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.delete("", response_model=SuccessResponse)
async def delete_package(
    package_id: str,
    package_service: PackageService = Depends(get_package_service),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.DELETE,
            CareProviderFeature.PACKAGES,
        )
    ),
):
    try:
        await package_service.delete_package(package_id=package_id)

        return SuccessResponse(
            message="Packages deleted successfully",
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
