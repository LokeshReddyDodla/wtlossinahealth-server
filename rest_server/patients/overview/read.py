import traceback
from datetime import date, datetime, time

from fastapi import Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (
    get_cgm_report_service,
    get_fitness_report_service,
    get_cgm_stats_processor,
    get_meal_report_service,
)
from lib.models.patient import Patient
from lib.services.reports import (
    CGMReportService,
    FitnessReportService,
    MealReportService,
    CGMStatsProcessor,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get(path="/stats", response_model=SuccessResponse)
async def get_patient_overview_api(
    request: Request,
    date: date = Query(...),
    meal_report_service: MealReportService = Depends(get_meal_report_service),
    fitness_report_service: FitnessReportService = Depends(
        get_fitness_report_service
    ),
    cgm_report_service: CGMReportService = Depends(get_cgm_report_service),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        patient_id = str(current_patient.patient_id)

        meal_report = await meal_report_service.fetch_daily_report(
            patient_id, date
        )

        fitness_report = await fitness_report_service.fetch_daily_report(
            patient_id, date
        )

        cgm_report = await cgm_report_service.fetch_daily_report(
            patient_id, date
        )

        return SuccessResponse(
            message="Patient stats fetched successfully",
            data={
                "meal_report": meal_report,
                "fitness_report": fitness_report,
                "cgm_report": cgm_report
            },
        )

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        error_message = f"Exception occurred: {str(e)}"
        traceback_message = traceback.format_exc()
        print("🚀 ~ error_message:", error_message)
        print("🚀 ~ traceback_message:", traceback_message)

        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
