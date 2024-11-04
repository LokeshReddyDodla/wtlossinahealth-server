from datetime import datetime
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import (get_patient_profile_service,
                                                   get_patient_smbg_service)
from lib.models.patient import Patient
from lib.models.patient_smbg import PatientSMBG
from lib.schemas.patient_smbg import PatientSMBG as PatientSMBGSchema
from lib.schemas.patient_smbg import PatientSMBGCreate
from lib.services.ai_conversation_service import AiConversationService
from lib.services.patient_profile_service import PatientProfileService
from lib.services.patient_smbg_service import PatientSmbgService
from rest_server.patients.smbgs.api_schema import (PatientSmbgUpload,
                                                   PatientSmbgUploadResponse)
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post("/upload", response_model=PatientSmbgUploadResponse)
async def upload_smbg(
    request: Request,
    smbg_data: PatientSMBGCreate,
    patient_smbg_service: PatientSmbgService = Depends(
        get_patient_smbg_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        new_smbg, ai_response_generated = (
            await patient_smbg_service.upload_patient_smbg(
                str(current_patient.patient_id), smbg_data
            )
        )

        smbg = PatientSMBGSchema.model_validate(new_smbg)

        return PatientSmbgUploadResponse(
            message="SMBG data uploaded successfully.",
            data=PatientSmbgUpload(
                smbg_data=smbg, ai_response_generated=ai_response_generated
            ),
        )
    except Exception as e:
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())
