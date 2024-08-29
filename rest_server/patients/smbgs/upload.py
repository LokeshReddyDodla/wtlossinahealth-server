from fastapi import APIRouter, HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient
from lib.models.patient_smbg import PatientSMBG
from lib.schemas.patient_smbg import (
    PatientSMBGCreate,
    PatientSMBG as PatientSMBGSchema,
)
from lib.schemas.patient_smbg import (
    PatientSMBG as PatientSMBGSchema,
)
from sqlalchemy.future import select
from rest_server.patients.smbgs.api_schema import PatientSmbgUploadResponse
from rest_server.response_models import SuccessResponse, ErrorResponse
from typing import Union
from datetime import datetime
from .router import router


@router.post(
    "/upload", tags=["SMBGs"], response_model=PatientSmbgUploadResponse
)
async def upload_smbg(
    request: Request,
    smbg: PatientSMBGCreate,
    current_patient: Patient = Depends(get_current_patient),
) -> Union[PatientSmbgUploadResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            new_smbg = PatientSMBG(
                patient_id=current_patient.patient_id,
                glucose_level=smbg.glucose_level,
                reading_time=smbg.reading_time,
                source=smbg.source,
                type=smbg.type,
                notes=smbg.notes,
            )
            session.add(new_smbg)
            await session.commit()
            await session.refresh(new_smbg)

            result = PatientSMBGSchema.from_orm(new_smbg)

            return PatientSmbgUploadResponse(
                message="SMBG data uploaded successfully.",
                data=result,
            )
        except Exception as e:
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())
