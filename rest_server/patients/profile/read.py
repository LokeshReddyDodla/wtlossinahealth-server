from typing import List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import get_patient_profile_service
from lib.models.care_provider import CareProvider
from lib.models.patient import Patient
from lib.models.patient_connected_app import PatientConnectedApp
from lib.schemas.patient import CompletePatientProfile
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.get(path="", response_model=SuccessResponse)
async def get_patient_details(
    request: Request,
    detailed: bool = False,
    include_health_data: bool = False,
    other_related_data: bool = False,
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        result = await patient_profile_service.fetch_patient_profile(
            str(current_patient.patient_id),
            detailed=detailed,
            include_health_data=include_health_data,
            other_related_data=other_related_data,
        )
        return SuccessResponse(
            message="Patient data fetched successfully.",
            data=CompletePatientProfile.from_orm(result),
        )
    except HTTPException as http_exc:
        raise http_exc
    except SQLAlchemyError as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Database Error",
            detail=str(e),
        )
