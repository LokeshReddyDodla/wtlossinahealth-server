from datetime import datetime
from fastapi import Depends, HTTPException, Request, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (
    get_patient_profile_service,
    get_patient_smbg_service,
    get_smbg_stats_processor,
)
from lib.models.patient import Patient
from lib.schemas.patient import CorePatientProfile
from lib.schemas.patient_smbg import PatientSMBG as PatientSMBGSchema
from lib.services.patient_profile_service import PatientProfileService
from lib.services.patient_smbg_service import PatientSmbgService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.smbg.processor import SMBGStatsProcessor
from rest_server.response_models import SuccessResponse
from lib.models.care_provider import CareProvider as CareProviderModel

from .router import router


@router.get("", response_model=SuccessResponse)
async def get_patient_smbg(
    request: Request,
    patient_id: str,
    patient_smbg_service: PatientSmbgService = Depends(
        get_patient_smbg_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ, CareProviderFeature.REPORTS
        )
    ),
):
    try:
        smbg_records = await patient_smbg_service.get_patient_smbgs(patient_id)
        smbgs = [
            PatientSMBGSchema.model_validate(record) for record in smbg_records
        ]

        return SuccessResponse(
            message="SMBG data fetched successfully.",
            data=smbgs,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get(
    "/reports/",
    response_model=SuccessResponse,
)
async def fetch_smbg_report_inrange(
    patient_id: str,
    start_date: datetime,
    end_date: datetime,
    smbg_stats_processor: SMBGStatsProcessor = Depends(
        get_smbg_stats_processor
    ),
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ, CareProviderFeature.REPORTS
        )
    ),
):
    try:
        patient_info = await patient_profile_service.fetch_patient_profile(
            patient_id=patient_id, include_health_data=True
        )
        report = await smbg_stats_processor.get_stats(
            patient_id, start_date, end_date
        )

        if not report:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="No SMBG data found for given range",
            )

        return SuccessResponse(
            message="SMBG report fetched successfully",
            data={
                "patient_info": CorePatientProfile.from_orm(patient_info),
                "report": report,
            },
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
