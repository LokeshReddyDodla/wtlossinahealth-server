"""Fitness report endpoints — daily, weekly, monthly."""

from datetime import date

from fastapi import Depends, HTTPException, Query, status

from lib.dependencies.report_access import ReportAccessInfo, get_report_access_info
from lib.dependencies.service_dependencies import get_fitness_report_service
from lib.services.reports import FitnessReportService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/daily", response_model=SuccessResponse)
async def get_daily_fitness_report(
    report_date: date = Query(..., description="YYYY-MM-DD"),
    regenerate: bool = Query(False),
    access_info: ReportAccessInfo = Depends(get_report_access_info),
    service: FitnessReportService = Depends(get_fitness_report_service),
):
    report = await service.fetch_daily_report(
        str(access_info.target_patient_id), report_date, regenerate=regenerate
    )
    if not report:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND,
            message="Fitness report not found. It may be generating.",
        )
    return SuccessResponse(message="Fitness report", data=report)


@router.get("/weekly", response_model=SuccessResponse)
async def get_weekly_fitness_report(
    year: int = Query(..., description="Year (e.g., 2026)"),
    week_no: int = Query(..., description="Week number (1-52)"),
    access_info: ReportAccessInfo = Depends(get_report_access_info),
    service: FitnessReportService = Depends(get_fitness_report_service),
):
    report = await service.fetch_weekly_report(
        str(access_info.target_patient_id), year, week_no
    )
    if not report:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND,
            message="Fitness report not found. It may be generating.",
        )
    return SuccessResponse(message="Fitness report", data=report)


@router.get("/monthly", response_model=SuccessResponse)
async def get_monthly_fitness_report(
    year: int = Query(..., description="Year (e.g., 2026)"),
    month_no: int = Query(..., ge=1, le=12, description="Month (1-12)"),
    access_info: ReportAccessInfo = Depends(get_report_access_info),
    service: FitnessReportService = Depends(get_fitness_report_service),
):
    report = await service.fetch_monthly_report(
        str(access_info.target_patient_id), year, month_no
    )
    if not report:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND,
            message="Fitness report not found. It may be generating.",
        )
    return SuccessResponse(message="Fitness report", data=report)
