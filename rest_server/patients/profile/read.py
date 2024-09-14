from typing import List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.care_provider import CareProvider
from lib.models.patient import Patient
from lib.models.patient_care_provider import PatientCareProvider
from lib.models.patient_connected_app import PatientConnectedApp
from lib.schemas.patient import CompletePatientProfile
from lib.services.patient_profile_service import PatientProfileService
from rest_server.patients.profile.api_schema import \
    PatientCompleteProfileResponse
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.get(path="", response_model=PatientCompleteProfileResponse)
async def get_patient_details(
    request: Request, current_patient: Patient = Depends(get_current_patient)
) -> Union[PatientCompleteProfileResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        service = PatientProfileService(session)
        try:
            result = await service.fetch_patient_profile(
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
