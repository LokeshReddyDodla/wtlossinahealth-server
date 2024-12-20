from typing import List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.models.patient import Patient
from lib.models.patient_connected_app import PatientConnectedApp
from lib.schemas.patient import Patient as PatientSchema
from lib.schemas.patient import PatientCreate, PatientUpdate
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post(path="/basic", response_model=SuccessResponse)
async def create_basic_patient(
    request: Request,
    patient_data: PatientCreate,
    session: AsyncSession = Depends(get_postgres_session),
):
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
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Patient already exists",
            )

        # Create a new patient
        new_patient = Patient(**patient_data.dict())
        session.add(new_patient)
        await session.commit()
        await session.refresh(new_patient)

        result = PatientSchema.from_orm(new_patient)

        return SuccessResponse(
            message="Patient basic data created successfully.",
            data=result,
        )
    except HTTPException as http_exc:
        raise http_exc
    except IntegrityError as e:
        await session.rollback()
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Integrity Error",
            detail=str(e),
        )
    except Exception as e:
        await session.rollback()
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
