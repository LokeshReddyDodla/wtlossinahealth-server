"""List fitness reports in a date range."""

from datetime import date

from fastapi import Depends, Query, status

from lib.dependencies.report_access import ReportAccessInfo, get_report_access_info
from lib.dependencies.service_dependencies import get_fitness_report_service
from lib.services.reports import FitnessReportService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .api_schema import FitnessReportListResponse, ListFitnessReportsResponse
from .router import router


@router.get("", response_model=ListFitnessReportsResponse)
async def list_fitness_reports(
    start_date: date = Query(..., description="YYYY-MM-DD"),
    end_date: date = Query(..., description="YYYY-MM-DD"),
    access_info: ReportAccessInfo = Depends(get_report_access_info),
    service: FitnessReportService = Depends(get_fitness_report_service),
):
    if end_date < start_date:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="end_date must be >= start_date",
        )

    reports = await service.fetch_daily_reports_in_range(
        str(access_info.target_patient_id), start_date, end_date
    )

    return SuccessResponse(
        message="Fitness reports",
        data=FitnessReportListResponse(reports=reports, total=len(reports)),
    )
