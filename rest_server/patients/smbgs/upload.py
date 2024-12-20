from datetime import datetime
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Request, status
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
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post("/upload", response_model=SuccessResponse)
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

        return SuccessResponse(
            message="SMBG data uploaded successfully.",
            data={
                "smbg_data": smbg,
                "ai_response_generated": ai_response_generated,
            },
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
