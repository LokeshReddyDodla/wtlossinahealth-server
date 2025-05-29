from fastapi import Depends, HTTPException, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_care_provider_profile_service,
    get_cgm_report_service,
    get_chat_management_service,
    get_patient_profile_service,
)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.patient import CompletePatientProfile
from lib.services.care_provider_profile_service import (
    CareProviderProfileService,
)
from lib.services.cgm_report_service import CGMReportService
from lib.services.chat.chat_management_service import ChatManagementService
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.care_provider.patients.profile.api_schema import (
    CareProviderPatients,
)
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("", response_model=SuccessResponse)
async def get_patients(
    care_provider_profile_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
    cgm_report_service: CGMReportService = Depends(get_cgm_report_service),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ, CareProviderFeature.PATIENTS
        )
    ),
):
    try:
        patients = (
            await care_provider_profile_service.fetch_care_provider_patients(
                str(current_care_provider.care_provider_id),
                str(current_care_provider.role).lower(),
                str(current_care_provider.health_facility_id),
            )
        )

        updated_patients = []

        for patient in patients:
            cgm_reports = await cgm_report_service.fetch_reports(
                str(patient.patient_id)
            )
            updated_patient = {
                **CareProviderPatients.from_orm(patient).model_dump(),
                "reports": {"cgm": cgm_reports},
            }
            updated_patients.append(updated_patient)

        return SuccessResponse(
            message="Patients fetched successfully",
            data=updated_patients,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get("/profile", response_model=SuccessResponse)
async def get_patient_profile(
    patient_id: str,
    detailed: bool = False,
    include_health_data: bool = False,
    other_related_data: bool = False,
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
    chat_management_service: ChatManagementService = Depends(
        get_chat_management_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ, CareProviderFeature.PATIENTS
        )
    ),
):
    try:
        profile = await patient_profile_service.fetch_patient_profile(
            patient_id,
            detailed=detailed,
            include_health_data=include_health_data,
            other_related_data=other_related_data,
        )

        direct_chat = await chat_management_service.find_direct_chat(
            patient_id, str(current_care_provider.care_provider_id)
        )

        return SuccessResponse(
            message="Patient profile fetched successfully",
            data={
                **CompletePatientProfile.from_orm(profile).model_dump(),
                "direct_chat_id": direct_chat,
            },
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
