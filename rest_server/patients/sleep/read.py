from datetime import date, datetime, time
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (get_patient_sleep_service,
                                                   get_patient_vital_service,
                                                   get_sleep_report_service,
                                                   get_sleep_stats_processor)
from lib.models.patient import Patient
from lib.schemas.patient_sleep import PatientSleepSchema
from lib.services.patient_sleep_service import PatientSleepService
from lib.services.sleep_report_service import SleepReportService
from lib.utils.date_utils import (get_month_start_end,
                                  get_week_start_and_end_from_week_no)
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.sleep.sleep_stats_processor import SleepStatsProcessor
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/day", response_model=SuccessResponse)
async def get_day_sleep_data(
    request: Request,
    date: date = Query(...),
    sleep_report_service: SleepReportService = Depends(
        get_sleep_report_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        report = await sleep_report_service.fetch_daily_report(
            str(current_patient.patient_id), date
        )

        return SuccessResponse(
            message="Day sleep report fetched successfully",
            data=jsonable_encoder(report),
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
    "/week",
)
async def get_week_sleep_data(
    request: Request,
    year: int,
    week_no: int,
    sleep_report_service: SleepReportService = Depends(
        get_sleep_report_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        start_date, end_date = get_week_start_and_end_from_week_no(
            year, week_no
        )
        weekly_report = await sleep_report_service.fetch_weekly_report(
            str(current_patient.patient_id), year, week_no
        )
        daily_report = await sleep_report_service.fetch_daily_reports_in_range(
            str(current_patient.patient_id), start_date, end_date
        )

        return SuccessResponse(
            message="Week sleep report fetched successfully",
            data={"overall": weekly_report, "day_wise": daily_report},
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
    "/month",
)
async def get_month_sleep_data(
    request: Request,
    year: int,
    month_no: int,
    sleep_report_service: SleepReportService = Depends(
        get_sleep_report_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        start_date, end_date = get_month_start_end(year, month_no)
        monthly_report = await sleep_report_service.fetch_monthly_report(
            str(current_patient.patient_id), year, month_no
        )
        daily_report = await sleep_report_service.fetch_daily_reports_in_range(
            str(current_patient.patient_id), start_date, end_date
        )

        return SuccessResponse(
            message="Month sleep report fetched successfully",
            data={"overall": monthly_report, "day_wise": daily_report},
        )

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
