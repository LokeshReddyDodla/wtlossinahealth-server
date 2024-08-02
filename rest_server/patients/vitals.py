from fastapi import APIRouter, HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient
from lib.models.patient_vitals import PatientVitals
from lib.schemas.patient_vitals import PatientVitalsCreate
from sqlalchemy.future import select
from rest_server.response_models import SuccessResponse, ErrorResponse
from typing import Union
from datetime import datetime

router = APIRouter(prefix="/patient")


@router.post("/vitals", tags=["Vitals"], response_model=SuccessResponse)
async def upload_vitals(
    request: Request,
    vitals: PatientVitalsCreate,
    current_patient: Patient = Depends(get_current_patient),
) -> Union[SuccessResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            new_vitals = PatientVitals(
                patient_id=current_patient.patient_id,
                test_time=vitals.test_time,
                a1c=vitals.a1c,
                creatinine=vitals.creatinine,
                diastolic_bp=vitals.diastolic_bp,
                heart_rate=vitals.heart_rate,
                ketones=vitals.ketones,
                respiratory_rate=vitals.respiratory_rate,
                spo2=vitals.spo2,
                systolic_bp=vitals.systolic_bp,
                temperature=vitals.temperature,
                weight=vitals.weight,
            )
            session.add(new_vitals)
            await session.commit()
            await session.refresh(new_vitals)
            return SuccessResponse(
                message="Vitals uploaded successfully.",
                data=new_vitals,
            )
        except Exception as e:
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())


@router.get("/vitals", tags=["Vitals"], response_model=SuccessResponse)
async def get_patient_vitals(
    request: Request, current_patient: Patient = Depends(get_current_patient)
) -> Union[SuccessResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            result = await session.execute(
                select(PatientVitals)
                .where(PatientVitals.patient_id == current_patient.patient_id)
                .order_by(PatientVitals.test_time.desc())
            )

            vitals = result.scalars().all()
            return SuccessResponse(
                message="Vitals fetched successfully.",
                data=vitals,
            )
        except Exception as e:
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())
