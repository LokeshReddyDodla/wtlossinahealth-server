from fastapi import APIRouter, HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient
from lib.models.patient_smbg import PatientSMBG
from lib.schemas.patient_smbg import (
    PatientSMBG as PatientSMBGSchema,
)
from sqlalchemy.future import select
from rest_server.patients.smbgs.api_schema import PatientSmbgsResponse
from rest_server.response_models import SuccessResponse, ErrorResponse
from typing import Union
from datetime import datetime

router = APIRouter()


@router.get("", tags=["SMBGs"], response_model=PatientSmbgsResponse)
async def get_patient_smbg(
    request: Request, current_patient: Patient = Depends(get_current_patient)
) -> Union[PatientSmbgsResponse, HTTPException]:
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

            return PatientSmbgsResponse(
                message="SMBG data fetched successfully.",
                data=smbgs,
            )
        except Exception as e:
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())
