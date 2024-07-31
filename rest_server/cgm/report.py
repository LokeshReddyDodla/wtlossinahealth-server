import traceback
from typing import Union
from datetime import datetime, timedelta
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select

from sqlalchemy.orm import selectinload

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient


from lib.utils.date.periods import DayWisePeriod, OverallPeriod, WeekWisePeriod

from lib.utils.glucose.processor import PeriodicStatsProcessor


from rest_server.cgm.api_schema import (
    GlucoseReportResponse,
)

# Create FastAPI router
router = APIRouter(prefix="/cgm/report")


@router.get(
    "/detailed_glucose_report",
    tags=["CGM"],
    response_model=GlucoseReportResponse,
)
async def get_detailed_glucose_report(
    request: Request,
    from_date: datetime = Query(...),
    to_date: datetime = Query(...),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        clickhouse_store = request.state.context.clickhouse_store

        patient_id = str(current_patient.patient_id)

        # Fetch patient details
        async with request.state.context.postgres_store.get_session() as postgres_session:
            processor = PeriodicStatsProcessor(
                clickhouse_store, postgres_session, patient_id
            )

            # Fetch patient details
            patient_detail = await processor.fetch_profile()

            # Overall Stats
            overall_period = OverallPeriod(from_date, to_date)
            overall_stats = await processor.process(overall_period.periods)

            # Day-wise Stats
            day_periods = DayWisePeriod(from_date, to_date)
            day_wise_stats = await processor.process(
                day_periods.periods, include_readings=True
            )

            # Week-wise Stats
            week_periods = WeekWisePeriod(from_date, to_date)
            week_wise_stats = await processor.process(
                week_periods.periods, include_readings=True
            )

            return GlucoseReportResponse(
                patient_detail=patient_detail,
                overall_stats=overall_stats,
                day_wise_stats=day_wise_stats,
                week_wise_stats=week_wise_stats,
            )

    except Exception as e:
        error_message = f"Exception occurred: {str(e)}"
        traceback_message = traceback.format_exc()
        print("🚀 ~ error_message:", error_message)
        print("🚀 ~ traceback_message:", traceback_message)
        response = {"message": "Internal Server Error", "detail": str(e)}
        raise HTTPException(status_code=500, detail=response)
