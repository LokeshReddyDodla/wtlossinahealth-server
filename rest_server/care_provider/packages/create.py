from fastapi import Depends, HTTPException, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_care_provider_profile_service, get_package_service)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.schemas.health_facility import HealthFacility as HealthFacilitySchema
from lib.schemas.package import Package as PackageSchema
from lib.schemas.package import PackageCreate
from lib.services.care_provider_profile_service import \
    CareProviderProfileService
from lib.services.package_service import PackageService
from lib.utils.care_provider_permissions import (CareProviderFeature,
                                                 CareProviderPermissionAction)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post("", response_model=SuccessResponse)
async def create_package(
    package: PackageCreate,
    package_service: PackageService = Depends(get_package_service),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.CREATE,
            CareProviderFeature.PACKAGES,
        )
    ),
):
    try:
        health_facility_id = current_care_provider.health_facility_id

        if not health_facility_id:  # type: ignore
            raise_http_exception(
                status_code=status.HTTP_403_FORBIDDEN,
                message="Care provider is not associated with any health facility.",
            )

        new_package = await package_service.create_package(
            package_data=package,
            health_facility_id=health_facility_id, # type: ignore
        )

        return SuccessResponse(
            message="Packages created  successfully",
            data=PackageSchema.from_orm(new_package),
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
