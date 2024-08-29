from fastapi import APIRouter, HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient

from sqlalchemy.future import select
from lib.models.patient_vital import PatientVital
from lib.schemas.patient_vital import PatientVital as PatientVitalSchema
from rest_server.patients.vitals.api_schema import PatientVitalsResponse
from rest_server.response_models import ErrorResponse
from typing import Union
from datetime import datetime
from .router import router


@router.get("", tags=["Vitals"], response_model=PatientVitalsResponse)
async def get_patient_vitals(
    request: Request, current_patient: Patient = Depends(get_current_patient)
) -> Union[PatientVitalsResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
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
