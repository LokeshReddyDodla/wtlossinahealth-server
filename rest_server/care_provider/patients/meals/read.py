from datetime import date

from fastapi import Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_meal_report_service,
    get_patient_profile_service,
)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.patient import CorePatientProfile
from lib.services.meal_report_service import MealReportService
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import InQueueResponse, SuccessResponse

from .router import router


@router.get("/report/day")
async def get_day_meal_report(
    request: Request,
    patient_id: str = Query(...),
    date: date = Query(...),
    regenerate: bool = Query(False),
    meal_report_service: MealReportService = Depends(get_meal_report_service),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ, CareProviderFeature.REPORTS
        )
    ),
):
    try:
        meal_report = await meal_report_service.fetch_daily_report(
            str(patient_id), date, regenerate=regenerate
        )

        if not meal_report:
            return InQueueResponse(
                message="Report is being generated. Please check back shortly.",
            )

        return SuccessResponse(
            message="Day Meal report fetched successfully",
            data=meal_report,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get("/report/range")
async def get_meal_reports_in_range(
    request: Request,
    patient_id: str = Query(...),
    start_date: date = Query(...),
    end_date: date = Query(...),
    meal_report_service: MealReportService = Depends(get_meal_report_service),
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
        # Validate date range
        if start_date > end_date:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Invalid date range",
                detail="Start date cannot be after end date",
            )

        patient_info = await patient_profile_service.fetch_patient_profile(
            patient_id=patient_id, include_health_data=True
        )

        reports = await meal_report_service.fetch_daily_reports_in_range(
            str(patient_id), start_date, end_date
        )

        return SuccessResponse(
            message=f"Successfully fetched reports from {start_date} to {end_date}",
            data={
                "patient_info": CorePatientProfile.from_orm(patient_info),
                "reports": reports,
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
