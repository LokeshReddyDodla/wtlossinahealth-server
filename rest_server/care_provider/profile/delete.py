from fastapi import Depends, HTTPException, Request, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_care_provider_profile_service,
)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.services.care_provider_profile_service import (
    CareProviderProfileService,
)
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.delete("/{care_provider_id}", response_model=SuccessResponse)
async def delete_profile(
    request: Request,
    care_provider_id: str,
    care_provider_profile_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.DELETE,
            CareProviderFeature.CARE_PROVIDERS,
        )
    ),
):
    try:
        await care_provider_profile_service.delete_care_provider(
            care_provider_id
        )

        return SuccessResponse(message="Care provider deleted successfully.")
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
