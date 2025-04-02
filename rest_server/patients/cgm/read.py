from datetime import date, datetime, time

from fastapi import Depends, Query, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_glucose_stats_processor
from lib.models.patient import Patient
from lib.utils.glucose.processor import GlucoseStatsProcessor
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/report/day", response_model=SuccessResponse)
async def get_cgm_day_report(
    request: Request,
    date: date = Query(...),
    glucose_stats_processor: GlucoseStatsProcessor = Depends(
        get_glucose_stats_processor
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        start_date = datetime.combine(date, time.min)  # Start of the day
        end_date = datetime.combine(date, time.max)  # End of the day

        glucose_stats = await glucose_stats_processor.generate_report(
            str(current_patient.patient_id), start_date, end_date
        )

        return SuccessResponse(
            message="Glucose report fetched successfully",
            data=glucose_stats["day_wise"][0],
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
