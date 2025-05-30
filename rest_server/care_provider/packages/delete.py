from fastapi import Depends, HTTPException, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import get_package_service
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.package import Package as PackageSchema
from lib.services.package_service import PackageService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

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
        await package_service.delete_package(
            package_id=package_id,
            health_facility_id=str(current_care_provider.health_facility_id),
        )

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


@router.delete("/remove-care-provider", response_model=SuccessResponse)
async def remove_care_provider_from_package(
    package_id: str,
    care_provider_id: str,
    package_service: PackageService = Depends(get_package_service),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.UPDATE,
            CareProviderFeature.PACKAGES,
        )
    ),
):
    try:
        package = await package_service.remove_care_provider_from_package(
            care_provider_id=care_provider_id,
            package_id=package_id,
            health_facility_id=str(current_care_provider.health_facility_id),
        )
        return SuccessResponse(
            message="Care Provider removed from the package successfully.",
            data=PackageSchema.from_orm(package),
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.delete("/remove-patient", response_model=SuccessResponse)
async def remove_patient_from_package(
    package_id: str,
    patient_id: str,
    package_service: PackageService = Depends(get_package_service),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.UPDATE,
            CareProviderFeature.PACKAGES,
        )
    ),
):
    try:
        package = await package_service.remove_patient_from_package(
            patient_id=patient_id, package_id=package_id
        )
        return SuccessResponse(
            message="Patient removed from the package successfully.",
            data=PackageSchema.from_orm(package),
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
