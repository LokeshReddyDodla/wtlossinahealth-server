from fastapi import APIRouter, HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient
from lib.models.patient_smbg import PatientSMBG
from lib.schemas.patient_smbg import (
    PatientSMBGCreate,
    PatientSMBG as PatientSMBGSchema,
)
from sqlalchemy.future import select
from rest_server.response_models import SuccessResponse, ErrorResponse
from typing import Union
from datetime import datetime

router = APIRouter(prefix="/patient")


@router.post("/smbg", tags=["SMBG"], response_model=SuccessResponse)
async def upload_smbg(
    request: Request,
    smbg: PatientSMBGCreate,
    current_patient: Patient = Depends(get_current_patient),
) -> Union[SuccessResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            new_smbg = PatientSMBG(
                patient_id=current_patient.patient_id,
                glucose_level=smbg.glucose_level,
                reading_time=smbg.reading_time,
                source=smbg.source,
                type=smbg.type,
                meal_type=smbg.meal_type,
                notes=smbg.notes,
            )
            session.add(new_smbg)
            await session.commit()
            await session.refresh(new_smbg)
            return SuccessResponse(
                message="SMBG data uploaded successfully.",
                data=new_smbg,
            )
        except Exception as e:
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())


@router.get("/smbg", tags=["SMBG"], response_model=SuccessResponse)
async def get_patient_smbg(
    request: Request, current_patient: Patient = Depends(get_current_patient)
) -> Union[SuccessResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            result = await session.execute(
                select(PatientSMBG)
                .where(PatientSMBG.patient_id == current_patient.patient_id)
                .order_by(PatientSMBG.reading_time.desc())
            )

            smbg_records = result.scalars().all()
            smbgs = [
                PatientSMBGSchema.from_orm(record) for record in smbg_records
            ]

            return SuccessResponse(
                message="SMBG data fetched successfully.",
                data=smbgs,
            )
        except Exception as e:
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())
