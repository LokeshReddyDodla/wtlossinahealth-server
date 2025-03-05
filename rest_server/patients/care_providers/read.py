import traceback
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (get_fitness_report_service,
                                                   get_glucose_stats_processor,
                                                   get_meal_report_service, get_patient_profile_service)
from lib.models.patient import Patient
from lib.schemas.care_provider import CareProvider
from lib.schemas.package import Package
from lib.services.fitness_report_service import FitnessReportService
from lib.services.meal_report_service import MealReportService
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.glucose.processor import GlucoseStatsProcessor
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router



@router.get(path="", response_model=SuccessResponse)
async def get_patient_care_providers_api(
    request: Request,
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        result = await patient_profile_service.fetch_patient_profile(
            str(current_patient.patient_id),
            
        )
         
        care_providers = [
            CareProvider.from_orm(careprovider).model_dump()
            for careprovider in (result.care_providers or [])
        ]
        
        return SuccessResponse(
            message="Patient care providers fetched successfully",
            data=care_providers,
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
