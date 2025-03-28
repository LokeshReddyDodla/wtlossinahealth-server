from fastapi import Depends, HTTPException, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_care_provider_profile_service, get_package_service)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.health_facility import HealthFacility as HealthFacilitySchema
from lib.services.care_provider_profile_service import \
    CareProviderProfileService
from lib.services.package_service import PackageService
from lib.utils.care_provider_permissions import (CareProviderFeature,
                                                 CareProviderPermissionAction)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.care_provider.health_facility.api_schema import (
    HealthFacilityCareProviders, HealthFacilityPackages)
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("", response_model=SuccessResponse)
async def get_health_facility(
    care_provider_profile_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ,
            CareProviderFeature.HEALTH_FACILITY,
        )
    ),
):
    try:
        care_provider = (
            await care_provider_profile_service.fetch_care_provider(
                str(current_care_provider.care_provider_id), detailed=True
            )
        )

        if not care_provider.health_facility_id:  # type: ignore
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="No health facility associated with the care provider.",
            )

        return SuccessResponse(
            message="Health facility details fetched successfully",
            data=HealthFacilitySchema.from_orm(care_provider.health_facility),
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get("/care-providers", response_model=SuccessResponse)
async def get_health_facility_care_providers(
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
        if not current_care_provider.health_facility_id:  # type: ignore
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="No health facility associated with the care provider.",
            )

        care_providers = await care_provider_profile_service.fetch_care_providers_in_health_facility(
            health_facility_id=str(current_care_provider.health_facility_id)
        )

        return SuccessResponse(
            message="Care providers in the health facility fetched successfully.",
            data=[
                HealthFacilityCareProviders.from_orm(cp)
                for cp in care_providers
            ],
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get("/packages", response_model=SuccessResponse)
async def get_health_facility_packages(
    package_service: PackageService = Depends(get_package_service),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ,
            CareProviderFeature.PACKAGES,
        )
    ),
):
    try:
        if not current_care_provider.health_facility_id:  # type: ignore
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="No health facility associated with the care provider.",
            )

        # Fetch packages in the same health facility
        packages = await package_service.fetch_packages_in_health_facility(
            health_facility_id=str(current_care_provider.health_facility_id)
        )

        return SuccessResponse(
            message="Packages in the health facility fetched successfully.",
            data=[HealthFacilityPackages.from_orm(pkg) for pkg in packages],
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
