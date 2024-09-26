from datetime import datetime
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.models.patient import Patient
from lib.models.patient_vital import PatientVital
from lib.schemas.patient_vital import PatientVital as PatientVitalSchema
from rest_server.patients.vitals.api_schema import PatientVitalsResponse
from rest_server.response_models import ErrorResponse

from .router import router


@router.get("", response_model=PatientVitalsResponse)
async def get_patient_vitals(
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
    current_patient: Patient = Depends(get_current_patient),
) -> Union[PatientVitalsResponse, HTTPException]:
    try:
        result = await session.execute(
            select(PatientVital)
            .where(PatientVital.patient_id == current_patient.patient_id)
            .order_by(PatientVital.test_time.desc())
        )

        vital_records = result.scalars().all()
        vitals = [
            PatientVitalSchema.from_orm(record) for record in vital_records
        ]
        return PatientVitalsResponse(
            message="Vitals fetched successfully.",
            data=vitals,
        )
    except Exception as e:
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())
