from datetime import datetime
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import get_patient_vital_service
from lib.models.patient import Patient
from lib.models.patient_vital import PatientVital
from lib.schemas.patient_vital import PatientVital as PatientVitalSchema
from lib.schemas.patient_vital import PatientVitalCreate
from lib.services.patient_vital_service import PatientVitalService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post("/upload", response_model=SuccessResponse)
async def upload_vitals(
    request: Request,
    vital_data: PatientVitalCreate,
    patient_vital_service: PatientVitalService = Depends(
        get_patient_vital_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        new_vitals = await patient_vital_service.upload_patient_vital(
            str(current_patient.patient_id),
            vital_data,
        )

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
