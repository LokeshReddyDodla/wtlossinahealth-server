from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import Session, selectinload

from lib.dependencies.auth.admin_auth import get_current_admin
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import \
    get_patient_connected_app_service
from lib.models.admin import Admin
from lib.models.patient_connected_app import \
    PatientConnectedApp as PatientConnectedAppModel
from lib.schemas.patient_connected_app import \
    PatientConnectedApp as PatientConnectedAppSchema
from lib.services.patient_connected_app_service import \
    PatientConnectedAppService
from rest_server.response_models import ErrorResponse, SuccessResponse

router = APIRouter(prefix="/admin/patient")


@router.get(
    "/connected-apps/libreview",
    tags=["Admin Patient"],
    response_model=SuccessResponse,
)
async def get_libreview_connected_patients(
    request: Request,
    patient_connected_app_service: PatientConnectedAppService = Depends(
        get_patient_connected_app_service
    ),
    current_admin: Admin = Depends(get_current_admin),
):
    try:
        connected_apps = (
            await patient_connected_app_service.get_all_connected_apps_with_libreview()
        )

        result = [
            PatientConnectedAppSchema.from_orm(app) for app in connected_apps
        ]

        return SuccessResponse(
            message="Connected apps fetched successfully.",
            data=result,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.model_dump())
