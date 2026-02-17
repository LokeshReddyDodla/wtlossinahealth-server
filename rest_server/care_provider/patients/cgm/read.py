from datetime import date

from fastapi import Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_cgm_report_service,
    get_patient_profile_service,
)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.patient import CorePatientProfile
from lib.services.reports import CGMReportService
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import InQueueResponse, SuccessResponse

from .router import router


@router.get(
    "/reports/{report_id}",
    response_model=SuccessResponse,
)
async def fetch_cgm_report(
    patient_id: str,
    report_id: str,
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


@router.get("/reports/day/{date}")
async def get_cgm_daily_report(
    patient_id: str,
    date: date,
    regenerate: bool = Query(False),
    cgm_report_service: CGMReportService = Depends(get_cgm_report_service),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ, CareProviderFeature.REPORTS
        )
    ),
):
    try:
        daily_report = await cgm_report_service.fetch_daily_report(
            patient_id,
            date,
        )

        if not daily_report:
            return InQueueResponse(
                message="CGM report is being generated. Please check back shortly.",
            )

        return SuccessResponse(
            message="Daily glucose report fetched successfully",
            data=daily_report,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
