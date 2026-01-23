from datetime import date
from typing import Optional

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

from .api_schema import (
    ListMealReportsResponse,
    MealReportListResponse,
    MealReportResponse,
)
from .router import router


@router.get(
    "",
    response_model=ListMealReportsResponse,
    summary="List Meal Reports",
    description=(
        "Get meal reports for a patient within a date range. "
        "If patient_id is not provided, fetches reports for the authenticated user (patients only). "
        "Patients can only fetch their own reports. "
        "Care providers must provide patient_id and can only fetch their assigned patients' reports. "
        "Admins can fetch any patient's reports."
    ),
)
async def list_meal_reports(
    start_date: date = Query(
        ..., description="Start date for report query (YYYY-MM-DD)"
    ),
    end_date: date = Query(
        ..., description="End date for report query (YYYY-MM-DD)"
    ),
    access_info: ReportAccessInfo = Depends(get_report_access_info),
    session: AsyncSession = Depends(get_postgres_session),
    meal_report_service: MealReportService = Depends(get_meal_report_service),
) -> ListMealReportsResponse:
    try:
        if end_date < start_date:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="End date must be greater than or equal to start date",
            )

        # Fetch reports
        reports = await meal_report_service.fetch_daily_reports_in_range(
            str(access_info.target_patient_id), start_date, end_date
        )

        report_responses = [
            MealReportResponse(
                date=date.fromisoformat(report.get("date")) if isinstance(report.get("date"), str) else report.get("date"),
                patient_id=str(access_info.target_patient_id),
                report_type=report.get("report_type", "daily"),
                data=report,
            )
            for report in reports
        ]

        return SuccessResponse(
            message="Meal reports retrieved successfully",
            data=MealReportListResponse(
                reports=report_responses,
                total=len(report_responses),
            ),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to retrieve meal reports",
            detail=str(e),
        )
