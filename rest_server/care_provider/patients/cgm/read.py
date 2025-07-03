from datetime import date

from fastapi import Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_cgm_report_service,
    get_patient_profile_service,
)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.patient import CorePatientProfile
from lib.services.cgm_report_service import CGMReportService
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get(
    "/report",
    response_model=SuccessResponse,
)
async def fetch_patient_cgm_report(
    request: Request,
    patient_id: str = Query(...),
    report_id: str = Query(...),
    cgm_report_service: CGMReportService = Depends(get_cgm_report_service),
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
        report = await cgm_report_service.fetch_report(patient_id, report_id)

        return SuccessResponse(
            message="Report fetched successfully",
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


@router.get("/report/day")
async def get_cgm_day_report(
    request: Request,
    patient_id: str = Query(...),
    date: date = Query(...),
    regenerate: bool = Query(False),
    cgm_report_service: CGMReportService = Depends(get_cgm_report_service),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ, CareProviderFeature.REPORTS
        )
    ),
):
    try:
        day_report = await cgm_report_service.fetch_day_report(
            patient_id, date, regenerate=regenerate
        )

        if not day_report:
            return SuccessResponse(
                message="CGM report is being generated. Please check back shortly.",
            )

        return SuccessResponse(
            message="Day Glucose report fetched successfully",
            data=day_report,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
