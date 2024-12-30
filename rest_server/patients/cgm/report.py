import traceback
import uuid
from datetime import datetime, timedelta
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (get_fitness_stats_processor,
                                                   get_glucose_stats_processor,
                                                   get_patient_profile_service)
from lib.models.patient import Patient
from lib.schemas.glucose_stats import (GlucoseDailyReport,
                                       GlucoseOverallReport,
                                       GlucoseWeeklyReport)
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.cgm_utils import CGMDataUtils
from lib.utils.date.periods import DayWisePeriod, OverallPeriod, WeekWisePeriod
from lib.utils.fitness.processor import FitnessStatsProcessor
from lib.utils.glucose.processor import GlucoseStatsProcessor
from lib.utils.http_exceptions import raise_http_exception
from rest_server.patients.cgm.api_schema import CompleteGlucoseReport
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.get(
    "/report",
    response_model=SuccessResponse,
)
async def get_patient_cgm_report(
    request: Request,
    patient_id: str = Query(...),
    from_date: datetime = Query(...),
    to_date: datetime = Query(...),
    fitness_stats_processor: FitnessStatsProcessor = Depends(
        get_fitness_stats_processor
    ),
    glucose_stats_processor: GlucoseStatsProcessor = Depends(
        get_glucose_stats_processor
    ),
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        clickhouse_store = request.state.context.clickhouse_store
        cgm_data_utils = CGMDataUtils(clickhouse_store)

        patient_id = str(current_patient.patient_id)

        # Check if data exists and is continuous within the provided date range
        if not await cgm_data_utils.is_data_available_and_continuous(
            patient_id, from_date, to_date
        ):
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="No continuous data available for the provided date range.",
            )

        # Fetch patient details
        from_date_str = from_date.strftime("%Y-%m-%dT%H:%M:%S")
        to_date_str = to_date.strftime("%Y-%m-%dT%H:%M:%S")

        # Fetch patient details
        patient_detail = await patient_profile_service.fetch_patient_profile(
            patient_id=patient_id
        )

        # Overall Stats
        overall_period = OverallPeriod(from_date, to_date)
        overall_stats = GlucoseOverallReport(
            cgm_report=await glucose_stats_processor.process(
                patient_id, overall_period.periods
            ),
            fitness_report=fitness_stats_processor.fetch_summary_stats(
                patient_id, from_date_str, to_date_str
            ),
        )

        # Day-wise Stats
        day_periods = DayWisePeriod(from_date, to_date)
        day_wise_stats = GlucoseDailyReport(
            cgm_report=await glucose_stats_processor.process(
                patient_id, day_periods.periods, include_readings=True
            ),
            fitness_report=fitness_stats_processor.fetch_daily_stats(
                str(current_patient.patient_id), from_date_str, to_date_str
            ),
        )

        # Week-wise Stats
        week_periods = WeekWisePeriod(from_date, to_date)
        week_wise_stats = GlucoseWeeklyReport(
            cgm_report=await glucose_stats_processor.process(
                patient_id, week_periods.periods, include_readings=True
            ),
            fitness_report=fitness_stats_processor.fetch_weekly_stats(
                patient_id, from_date_str, to_date_str
            ),
        )

        return SuccessResponse(
            message="Report generated successfully",
            data=CompleteGlucoseReport(
                patient_detail=patient_detail,
                overall_stats=overall_stats,
                day_wise_stats=day_wise_stats,
                week_wise_stats=week_wise_stats,
            ),
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
