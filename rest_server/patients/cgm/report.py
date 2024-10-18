import traceback
import uuid
from datetime import datetime, timedelta
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (get_fitness_processor,
                                                   get_glucose_processor)
from lib.models.patient import Patient
from lib.schemas.glucose_stats import (GlucoseDailyReport,
                                       GlucoseOverallReport,
                                       GlucoseWeeklyReport)
from lib.utils.cgm_utils import CGMDataUtils
from lib.utils.date.periods import DayWisePeriod, OverallPeriod, WeekWisePeriod
from lib.utils.fitness.processor import FitnessStatsProcessor
from lib.utils.glucose.processor import GlucoseStatsProcessor
from rest_server.patients.cgm.api_schema import (CompleteGlucoseReport,
                                                 GlucoseReportResponse)
from rest_server.response_models import ErrorResponse

from .router import router


@router.get(
    "/report",
    response_model=GlucoseReportResponse,
)
async def get_detailed_glucose_report(
    request: Request,
    from_date: datetime = Query(...),
    to_date: datetime = Query(...),
    fitness_processor: FitnessStatsProcessor = Depends(get_fitness_processor),
    glucose_processor: GlucoseStatsProcessor = Depends(get_glucose_processor),
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
            response = ErrorResponse(
                message="No continuous data available for the provided date range."
            )
            raise HTTPException(status_code=400, detail=response.dict())

        # Fetch patient details
        from_date_str = from_date.strftime("%Y-%m-%dT%H:%M:%S")
        to_date_str = to_date.strftime("%Y-%m-%dT%H:%M:%S")

        # Fetch patient details
        patient_detail = await glucose_processor.fetch_profile()

        # Overall Stats
        overall_period = OverallPeriod(from_date, to_date)
        overall_stats = GlucoseOverallReport(
            cgm_report=await glucose_processor.process(overall_period.periods),
            fitness_report=fitness_processor.fetch_summary_stats(
                from_date_str, to_date_str
            ),
        )

        # Day-wise Stats
        day_periods = DayWisePeriod(from_date, to_date)
        day_wise_stats = GlucoseDailyReport(
            cgm_report=await glucose_processor.process(
                day_periods.periods, include_readings=True
            ),
            fitness_report=fitness_processor.fetch_daily_stats(
                from_date_str, to_date_str
            ),
        )

        # Week-wise Stats
        week_periods = WeekWisePeriod(from_date, to_date)
        week_wise_stats = GlucoseWeeklyReport(
            cgm_report=await glucose_processor.process(
                week_periods.periods, include_readings=True
            ),
            fitness_report=fitness_processor.fetch_weekly_stats(
                from_date_str, to_date_str
            ),
        )

        return GlucoseReportResponse(
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
        response = {"message": "Internal Server Error", "detail": str(e)}
        raise HTTPException(status_code=500, detail=response)
