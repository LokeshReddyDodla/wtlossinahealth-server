from sqlalchemy import or_

from lib.models.care_provider import CareProvider
from lib.models.patient import Patient
from lib.models.patient_care_provider import PatientCareProvider
from lib.models.patient_connected_app import PatientConnectedApp

from fastapi import APIRouter, HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.future import select

from typing import List, Optional, Union
from sqlalchemy.exc import IntegrityError

from lib.schemas.patient import CompletePatientProfile
from lib.services.patient_profile_service import PatientService
from rest_server.patients.profile.api_schema import (
    PatientCompleteProfileResponse,
)
from rest_server.response_models import SuccessResponse, ErrorResponse
from .router import router


@router.get(path="", response_model=PatientCompleteProfileResponse)
async def get_patient_details(
    request: Request, current_patient: Patient = Depends(get_current_patient)
) -> Union[PatientCompleteProfileResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        service = PatientService(session)
        try:
            result = service.fetch_patient_profile(
                str(current_patient.patient_id), detailed=True
            )
            return PatientCompleteProfileResponse(
                message="Patient data fetched successfully.",
                data=CompletePatientProfile.from_orm(result),
            )
        except HTTPException as http_exc:
            raise http_exc
        except SQLAlchemyError as e:
            response = ErrorResponse(message="Database Error", detail=str(e))
            raise HTTPException(status_code=500, detail=response.dict())
