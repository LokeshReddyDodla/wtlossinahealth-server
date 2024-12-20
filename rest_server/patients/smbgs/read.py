from datetime import datetime
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import get_patient_smbg_service
from lib.models.patient import Patient
from lib.models.patient_smbg import PatientSMBG
from lib.schemas.patient_smbg import PatientSMBG as PatientSMBGSchema
from lib.services.patient_smbg_service import PatientSmbgService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.get("", response_model=SuccessResponse)
async def get_patient_smbg(
    request: Request,
    patient_smbg_service: PatientSmbgService = Depends(
        get_patient_smbg_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        smbg_records = await patient_smbg_service.get_patient_smbgs(
            str(current_patient.patient_id)
        )
        smbgs = [
            PatientSMBGSchema.model_validate(record) for record in smbg_records
        ]

        return SuccessResponse(
            message="SMBG data fetched successfully.",
            data=smbgs,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
