from sqlalchemy import or_
from lib.models.patient import (
    Patient,
)
from lib.models.patient_connected_app import PatientConnectedApp
from lib.schemas.patient import (
    PatientCreate,
    PatientUpdate,
    Patient as PatientSchema,
)
from fastapi import APIRouter, HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.future import select

from typing import List, Optional, Union
from sqlalchemy.exc import IntegrityError

from rest_server.patients.profile.api_schema import PatientProfileResponse
from rest_server.response_models import SuccessResponse, ErrorResponse

router = APIRouter()


@router.post(
    path="/basic", tags=["Profile"], response_model=PatientProfileResponse
)
async def create_basic_patient(
    request: Request,
    patient_data: PatientCreate,
) -> Union[PatientProfileResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            # Check if the patient already exists
            existing_patient = await session.execute(
                select(Patient).filter(
                    or_(
                        Patient.email == patient_data.email,
                        Patient.phone_number == patient_data.phone_number,
                    )
                )
            )
            existing_patient = existing_patient.scalar_one_or_none()

            if existing_patient:
                response = ErrorResponse(message="Patient already exists")
                raise HTTPException(status_code=400, detail=response.dict())

            # Create a new patient
            new_patient = Patient(**patient_data.dict())
            session.add(new_patient)
            await session.commit()
            await session.refresh(new_patient)

            result = PatientSchema.from_orm(new_patient)

            return PatientProfileResponse(
                message="Patient basic data created successfully.",
                data=result,
            )
        except HTTPException as http_exc:
            raise http_exc
        except IntegrityError as e:
            await session.rollback()
            response = ErrorResponse(message="Integrity Error", detail=str(e))
            raise HTTPException(status_code=400, detail=response.dict())
        except Exception as e:
            await session.rollback()
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())
