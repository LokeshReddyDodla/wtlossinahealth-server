from datetime import datetime
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.models.patient import Patient
from lib.models.patient_vital import PatientVital
from lib.schemas.patient_vital import PatientVital as PatientVitalSchema
from lib.schemas.patient_vital import PatientVitalCreate
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post("/upload", response_model=SuccessResponse)
async def upload_vitals(
    request: Request,
    vitals: PatientVitalCreate,
    session: AsyncSession = Depends(get_postgres_session),
    current_patient: Patient = Depends(get_current_patient),
):
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

        vital = PatientVitalSchema.model_validate(new_vitals)

        return SuccessResponse(
            message="Vitals uploaded successfully.",
            data=vital,
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
