from datetime import date, datetime

from fastapi import Depends, Query, Request, status
from fastapi.encoders import jsonable_encoder

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (
    get_fitness_report_service,
    get_fitness_stats_processor,
)
from lib.models.patient import Patient
from lib.services.fitness_report_service import FitnessReportService
from lib.utils.date_utils import (
    get_month_start_end,
    get_week_start_and_end_from_week_no,
)
from lib.utils.fitness.processor import FitnessStatsProcessor
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get(
    "/report",
    response_model=SuccessResponse,
)
async def get_fitness_stats(
    request: Request,
    start_date: datetime = Query(...),
    end_date: datetime = Query(...),
    fitness_processor: FitnessStatsProcessor = Depends(
        get_fitness_stats_processor
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        report = fitness_processor.generate_report(
            str(current_patient.patient_id),
            start_date,
            end_date,
            include_overall=True,
            include_day_wise=True,
            include_week_wise=True,
        )
        return SuccessResponse(
            message="Fitness report fetched successfully",
            data=report,
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get(
    "/report/day",
)
async def get_day_fitness_report(
    request: Request,
    date: date = Query(...),
    fitness_report_service: FitnessReportService = Depends(
        get_fitness_report_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        report = await fitness_report_service.fetch_daily_report(
            str(current_patient.patient_id), date
        )

        if not report:
            return SuccessResponse(
                message="Report is being generated. Please check back shortly.",
            )

        return SuccessResponse(
            message="Day fitness report fetched successfully",
            data=jsonable_encoder(report),
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get(
    "/report/week",
)
async def get_week_fitness_report(
    request: Request,
    year: int = Query(...),
    week_no: int = Query(...),
    fitness_report_service: FitnessReportService = Depends(
        get_fitness_report_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        start_date, end_date = get_week_start_and_end_from_week_no(
            year, week_no
        )
        weekly_report = await fitness_report_service.fetch_weekly_report(
            str(current_patient.patient_id), year, week_no
        )
        daily_report = (
            await fitness_report_service.fetch_daily_reports_in_range(
                str(current_patient.patient_id), start_date, end_date
            )
        )

        if not weekly_report or not daily_report:
            return SuccessResponse(
                message="Report is being generated. Please check back shortly.",
            )

        return SuccessResponse(
            message="Week fitness report fetched successfully",
            data={"overall": weekly_report, "day_wise": daily_report},
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get(
    "/report/month",
)
async def get_month_fitness_report(
    request: Request,
    year: int = Query(...),
    month_no: int = Query(...),
    fitness_report_service: FitnessReportService = Depends(
        get_fitness_report_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        start_date, end_date = get_month_start_end(year, month_no)
        monthly_report = await fitness_report_service.fetch_monthly_report(
            str(current_patient.patient_id), year, month_no
        )
        daily_report = (
            await fitness_report_service.fetch_daily_reports_in_range(
                str(current_patient.patient_id), start_date, end_date
            )
        )

        if not monthly_report or not daily_report:
            return SuccessResponse(
                message="Report is being generated. Please check back shortly.",
            )

        return SuccessResponse(
            message="Month fitness report fetched successfully",
            data={"overall": monthly_report, "day_wise": daily_report},
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
