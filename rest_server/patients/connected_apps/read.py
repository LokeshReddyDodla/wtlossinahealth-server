from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.models.patient import Patient
from lib.models.patient_connected_app import PatientConnectedApp
from lib.schemas.patient_connected_app import \
    PatientConnectedApp as PatientConnectedAppSchema
from rest_server.patients.connected_apps.api_schema import \
    GetPatientConnectedAppsResponse
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.get("", response_model=GetPatientConnectedAppsResponse)
async def get_patient_connected_apps(
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
    current_patient: Patient = Depends(get_current_patient),
) -> Union[GetPatientConnectedAppsResponse, HTTPException]:
    try:
        result = await session.execute(
            select(PatientConnectedApp)
            .where(
                PatientConnectedApp.patient_id == current_patient.patient_id
            )
            .options(
                selectinload(PatientConnectedApp.libreview),
            )
        )

        connected_apps = result.scalars().all()

        result = [
            PatientConnectedAppSchema.from_orm(record)
            for record in connected_apps
        ]

        return GetPatientConnectedAppsResponse(
            message="Connected apps fetched successfully.",
            data=result,
        )
    except Exception as e:
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())
