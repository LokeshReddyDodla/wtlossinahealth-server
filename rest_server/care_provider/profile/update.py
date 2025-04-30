from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import get_care_provider_profile_service
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.schemas.care_provider import CareProviderPermissions, CareProviderUpdate
from lib.services.care_provider_profile_service import CareProviderProfileService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.care_provider.profile.api_schema import SetPasswordRequest
from rest_server.response_models import SuccessResponse

from .router import router


@router.put("", response_model=SuccessResponse)
async def update_care_provider_profile(
    request: Request,
    care_provider_update: CareProviderUpdate,
    care_provider_profile_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.UPDATE,
            CareProviderFeature.CARE_PROVIDERS,
        )
    ),
):
    try:
        updated_care_provider = (
            await care_provider_profile_service.update_care_provider(
                str(current_care_provider.care_provider_id), care_provider_update
            )
        )

        return SuccessResponse(
            message="Care provider updated successfully.",
            data=CareProviderSchema.from_orm(updated_care_provider),
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.put("/set-password", response_model=SuccessResponse)
async def set_care_provider_password(
    request_data: SetPasswordRequest,
    care_provider_profile_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.UPDATE,
            CareProviderFeature.CARE_PROVIDERS,
        )
    ),
):
    try:
        await care_provider_profile_service.set_care_provider_password(
            care_provider_id=str(current_care_provider.care_provider_id),
            raw_password=request_data.raw_password,
        )

        return SuccessResponse(message="Password set successfully.")
    except HTTPException as e:
        raise e
    except IntegrityError as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to set password due to a conflict.",
            detail=str(e),
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.patch("/permissions", response_model=SuccessResponse)
async def update_care_provider_permissions(
    care_provider_id: str,
    permissions_update: CareProviderPermissions,
    care_provider_profile_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.UPDATE,
            CareProviderFeature.CARE_PROVIDERS,
        )
    ),
):
    try:
        _ = await care_provider_profile_service.update_care_provider_permissions(
            care_provider_id, permissions_update.root
        )
        return SuccessResponse(message="Permissions updated successfully.")
    except HTTPException as e:
        raise e
    except IntegrityError as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to set password due to a conflict.",
            detail=str(e),
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
