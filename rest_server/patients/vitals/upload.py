from fastapi import APIRouter, HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient

from sqlalchemy.future import select
from lib.models.patient_vital import PatientVital
from lib.schemas.patient_vital import (
    PatientVitalCreate,
    PatientVital as PatientVitalSchema,
)
from rest_server.patients.vitals.api_schema import PatientVitalUploadResponse
from rest_server.response_models import SuccessResponse, ErrorResponse
from typing import Union
from datetime import datetime

router = APIRouter()


@router.post(
    "/upload", tags=["Vitals"], response_model=PatientVitalUploadResponse
)
async def upload_vitals(
    request: Request,
    vitals: PatientVitalCreate,
    current_patient: Patient = Depends(get_current_patient),
) -> Union[PatientVitalUploadResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            new_vitals = PatientVital(
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
                source=vitals.source,
            )
            session.add(new_vitals)
            await session.commit()
            await session.refresh(new_vitals)

            vital = PatientVitalSchema.from_orm(new_vitals)

            return PatientVitalUploadResponse(
                message="Vitals uploaded successfully.",
                data=vital,
            )
        except Exception as e:
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())
