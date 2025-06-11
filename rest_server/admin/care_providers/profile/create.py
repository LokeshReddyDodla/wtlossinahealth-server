from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError

from lib.dependencies.auth.admin_auth import get_current_admin
from lib.dependencies.service_dependencies import (
    get_care_provider_profile_service,
)
from lib.models.admin import Admin
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.schemas.care_provider import CareProviderCreate
from lib.services.care_provider_profile_service import (
    CareProviderProfileService,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post("/profile", response_model=SuccessResponse)
async def create_care_provider_profile(
    request: Request,
    health_facility_id: str,
    care_provider: CareProviderCreate,
    care_provider_profile_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
    current_admin: Admin = Depends(get_current_admin),
):
    try:
        new_care_provider = (
            await care_provider_profile_service.create_care_provider(
                care_provider, health_facility_id
            )
        )

        return SuccessResponse(
            message="Care Provider created successfully",
            data=CareProviderSchema.from_orm(new_care_provider),
        )
    except HTTPException as e:
        raise e
    except SQLAlchemyError as e:
        response = ErrorResponse(message="Database Error", detail=str(e))
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Database Error",
            detail=str(e),
        )
