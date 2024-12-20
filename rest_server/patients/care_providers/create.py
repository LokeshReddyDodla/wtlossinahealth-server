from fastapi import Depends, HTTPException, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (
    get_care_provider_profile_service, get_health_facility_service,
    get_patient_profile_service)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.models.patient import Patient as PatientModel
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.services.care_provider_profile_service import \
    CareProviderProfileService
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.care_provider_permissions import (CareProviderFeature,
                                                 CareProviderPermissionAction)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post("/add-by-code", response_model=SuccessResponse)
async def add_care_provider_by_code(
    care_provider_code: str,
    patient_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
    current_patient: PatientModel = Depends(get_current_patient),
):

    try:
        care_provider = await patient_service.add_care_provider_by_code(
            patient_id=str(current_patient.patient_id),
            care_provider_code=care_provider_code,
        )

        return SuccessResponse(
            message="Care provider added successfully.",
            data={
                "care_provider_id": str(care_provider.care_provider_id),
                "name": f"{care_provider.first_name} {care_provider.last_name}",
            },
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=500,
            message="Internal Server Error",
            detail=str(e),
        )
