from fastapi import Depends, HTTPException, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_care_provider_profile_service, get_health_facility_service)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.services.care_provider_profile_service import \
    CareProviderProfileService
from lib.utils.care_provider_permissions import (CareProviderFeature,
                                                 CareProviderPermissionAction)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.get("", response_model=SuccessResponse)
async def get_care_provider_patients(
    care_provider_profile_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ, CareProviderFeature.PATIENTS
        )
    ),
):
    try:
        patients = (
            await care_provider_profile_service.fetch_care_provider_patients(
                str(current_care_provider.care_provider_id)
            )
        )
        print("==> patients: ", patients)

        for patient in patients:
            print(f"Patient: {patient.first_name} {patient.last_name}")
            print(f"care_provider: {patient.care_providers}")

            for care_provider in patient.care_providers:
                print(
                    f"  Care Provider: {care_provider.first_name} {care_provider.last_name}"
                )

        return SuccessResponse(
            message="Patients fetched successfully",
            data=patients,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
