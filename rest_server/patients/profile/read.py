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
        try:
            result = await session.execute(
                select(Patient)
                .where(Patient.patient_id == current_patient.patient_id)
                .options(
                    selectinload(Patient.daily_activity),
                    selectinload(Patient.food_allergies),
                    selectinload(Patient.drug_allergies),
                    selectinload(Patient.diet_preferences),
                    selectinload(Patient.alcohol_consumption),
                    selectinload(Patient.smoking_habit),
                    selectinload(Patient.meal_timings),
                    selectinload(Patient.cuisine_preferences),
                    selectinload(Patient.sleep_habit),
                    selectinload(Patient.diabetic_history),
                    selectinload(Patient.family_diabetic_histories),
                    selectinload(Patient.medical_histories),
                    selectinload(Patient.current_medication),
                    selectinload(Patient.permissions),
                    selectinload(Patient.vitals),
                    selectinload(Patient.smbgs),
                    selectinload(Patient.connected_apps).selectinload(
                        PatientConnectedApp.libreview
                    ),
                    selectinload(Patient.connected_apps).selectinload(
                        PatientConnectedApp.other_app
                    ),
                    selectinload(Patient.fitness_sync),
                    selectinload(Patient.token_usage_logs),
                    selectinload(Patient.care_providers)
                    .selectinload(PatientCareProvider.care_provider)
                    .selectinload(CareProvider.health_facility),
                    selectinload(Patient.health_facility),
                )
            )

            patient = result.scalars().first()
            if patient is None:
                raise HTTPException(
                    status_code=404, detail="Patient not found"
                )

            patient_profile = CompletePatientProfile.from_orm(patient)
            print(
                f"Serialized HealthFacility: {patient_profile.health_facility}"
            )

            return PatientCompleteProfileResponse(
                message="Patient data fetched successfully.",
                data=patient_profile,
            )
        except HTTPException as http_exc:
            raise http_exc
        except Exception as e:
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())
