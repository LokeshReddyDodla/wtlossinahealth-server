from datetime import date

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from lib.dependencies.database import get_postgres_session
from lib.dependencies.report_access import (
    ReportAccessInfo,
    get_report_access_info,
)
from lib.dependencies.service_dependencies import get_meal_report_service
from lib.services.meal_report_service import MealReportService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .api_schema import GetMealReportResponse, MealReportResponse
from .router import router


@router.get(
    "/daily",
    response_model=GetMealReportResponse,
    summary="Get Daily Meal Report",
    description=(
        "Get a daily meal report for a specific date. "
        "If patient_id is not provided, fetches report for the authenticated user (patients only). "
        "Patients can only fetch their own reports. "
        "Care providers must provide patient_id and can only fetch their assigned patients' reports. "
        "Admins can fetch any patient's reports."
    ),
)
async def get_daily_meal_report(
    report_date: date = Query(
        ..., description="Date for the daily report (YYYY-MM-DD)"
    ),
    regenerate: bool = Query(
        False, description="Whether to regenerate the report if it doesn't exist"
    ),
    access_info: ReportAccessInfo = Depends(get_report_access_info),
    session: AsyncSession = Depends(get_postgres_session),
    meal_report_service: MealReportService = Depends(get_meal_report_service),
) -> GetMealReportResponse:
    try:
        # Fetch report
        report = await meal_report_service.fetch_daily_report(
            str(access_info.target_patient_id), report_date, regenerate=regenerate
        )

        if not report:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Meal report not found. It may be generating.",
            )

        return SuccessResponse(
            message="Meal report retrieved successfully",
            data=MealReportResponse(
                date=report_date,
                patient_id=str(access_info.target_patient_id),
                report_type="daily",
                data=report,
            ),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to retrieve meal report",
            detail=str(e),
        )
