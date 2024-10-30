from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import \
    get_patient_connected_app_service
from lib.models.patient import Patient
from lib.models.patient_connected_app import (PatientConnectedApp,
                                              PatientLibreView)
from lib.schemas.patient_connected_app import \
    PatientLibreView as PatientLibreViewSchema
from lib.schemas.patient_connected_app import PatientLibreViewCreate
from lib.services.patient_connected_app_service import \
    PatientConnectedAppService
from rest_server.patients.connected_apps.api_schema import \
    UpdateLibreViewResponse
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post(
    "/update-libreview",
    response_model=UpdateLibreViewResponse,
)
async def update_libreview(
    request: Request,
    libreview_data: PatientLibreViewCreate,
    patient_connected_app_service: PatientConnectedAppService = Depends(
        get_patient_connected_app_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        libreview = (
            await patient_connected_app_service.add_or_update_libreview(
                libreview_data=libreview_data,
                patient_id=str(current_patient.patient_id),
            )
        )

        libreview = PatientLibreViewSchema.model_validate(libreview)

        return UpdateLibreViewResponse(
            message="LibreView data updated successfully.",
            data=libreview,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.model_dump())
