import traceback
import uuid
from datetime import datetime, timedelta
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (get_glucose_stats_processor,
                                                   get_patient_profile_service)
from lib.models.patient import Patient
from lib.schemas.patient import CorePatientProfile
from lib.services.patient_connected_app_service import \
    PatientConnectedAppService
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.cgm_utils import CGMDataUtils
from lib.utils.glucose.processor import GlucoseStatsProcessor
from lib.utils.http_exceptions import raise_http_exception
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

        # Fetch patient info
        patient_info = await patient_profile_service.fetch_patient_profile(
            patient_id=patient_id, include_health_data=True
        )

        report = await glucose_stats_processor.generate_report(
            patient_id, from_date, to_date
        )

        return SuccessResponse(
            message="Report generated successfully",
            data={
                "patient_info": CorePatientProfile.from_orm(patient_info),
                "report": report,
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
