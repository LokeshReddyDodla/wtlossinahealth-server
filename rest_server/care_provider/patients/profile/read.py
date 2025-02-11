from fastapi import Depends, HTTPException, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import \
    get_care_provider_profile_service,get_cgm_report_service
    
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.services.care_provider_profile_service import \
    CareProviderProfileService
from lib.services.cgm_report_service import CGMReportService
from lib.utils.care_provider_permissions import (CareProviderFeature,
                                                 CareProviderPermissionAction)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.care_provider.patients.profile.api_schema import \
    CareProviderPatients
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
                str(current_care_provider.care_provider_id)
            )
        )
        
        updated_patients = []
        
        for patient in patients:
            cgm_reports = await cgm_report_service.fetch_reports(
                str(patient.patient_id)
            )
            updated_patient = {
                **CareProviderPatients.from_orm(patient).model_dump(),
                "reports": {
                    "cgm": cgm_reports
                },
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
