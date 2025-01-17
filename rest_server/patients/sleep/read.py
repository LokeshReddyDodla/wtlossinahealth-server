from datetime import date, datetime
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (get_patient_sleep_service,
                                                   get_patient_vital_service)
from lib.models.patient import Patient
from lib.schemas.patient_sleep import PatientSleepSchema
from lib.services.patient_sleep_service import PatientSleepService
from lib.utils.date_utils import (get_month_start_end,
                                  get_week_start_and_end_from_week_no)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/daily", response_model=SuccessResponse)
async def get_daily_sleep_data(
    request: Request,
    date: date = Query(...),
    patient_sleep_service: PatientSleepService = Depends(
        get_patient_sleep_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        sleep_records = await patient_sleep_service.get_daily_sleep_data(
            str(current_patient.patient_id), date
        )

        return SuccessResponse(
            message="Daily sleep data fetched successfully", data=sleep_records
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
    "/weekly",
)
async def get_weekly_sleep_data(
    request: Request,
    year: int,
    week_no: int,
    patient_sleep_service: PatientSleepService = Depends(
        get_patient_sleep_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        start_datetime, end_datetime = get_week_start_and_end_from_week_no(
            year, week_no
        )

        sleep_records = await patient_sleep_service.get_daily_report_in_range(
            str(current_patient.patient_id), start_datetime, end_datetime
        )

        return SuccessResponse(
            message="Weekly sleep data fetched successfully",
            data=sleep_records,
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
    "/monthly",
)
async def get_monthly_sleep_data(
    request: Request,
    year: int,
    month_no: int,
    patient_sleep_service: PatientSleepService = Depends(
        get_patient_sleep_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        start_datetime, end_datetime = get_month_start_end(year, month_no)

        sleep_records = await patient_sleep_service.get_daily_report_in_range(
            str(current_patient.patient_id), start_datetime, end_datetime
        )

        return SuccessResponse(
            message="Monthly sleep data fetched successfully",
            data=sleep_records,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
