from fastapi import Depends, HTTPException, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import get_package_service
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.package import Package as PackageSchema, PackageUpdate
from lib.services.package_service import PackageService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.patch("/{package_id}", response_model=SuccessResponse)
async def update_package(
    package_id: str,
    updates: PackageUpdate,
    package_service: PackageService = Depends(get_package_service),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.UPDATE,
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

        updated_package = await package_service.update_package(
            package_id=package_id,
            updates=updates,
        )

        return SuccessResponse(
            message="Packages updated successfully",
            data=PackageSchema.from_orm(updated_package),
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
