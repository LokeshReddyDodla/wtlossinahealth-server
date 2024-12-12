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
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.get("", response_model=SuccessResponse)
async def get_patient_vitals(
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        result = await session.execute(
            select(PatientVital)
            .where(PatientVital.patient_id == current_patient.patient_id)
            .order_by(PatientVital.test_time.desc())
        )

        vital_records = result.scalars().all()
        vitals = [
            PatientVitalSchema.model_validate(record)
            for record in vital_records
        ]
        return SuccessResponse(
            message="Vitals fetched successfully.",
            data=vitals,
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
