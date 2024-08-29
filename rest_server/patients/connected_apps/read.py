from fastapi import APIRouter, HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient_connected_app import (
    PatientConnectedApp,
)
from lib.models.patient import Patient
from sqlalchemy.future import select
from rest_server.patients.connected_apps.api_schema import (
    GetPatientConnectedAppsResponse,
)
from lib.schemas.patient_connected_app import (
    PatientConnectedApp as PatientConnectedAppSchema,
)
from rest_server.response_models import SuccessResponse, ErrorResponse
from typing import Union
from sqlalchemy.orm import selectinload
from .router import router


@router.get(
    "", tags=["ConnectedApps"], response_model=GetPatientConnectedAppsResponse
)
async def get_patient_connected_apps(
    request: Request, current_patient: Patient = Depends(get_current_patient)
) -> Union[GetPatientConnectedAppsResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            result = await session.execute(
                select(PatientConnectedApp)
                .where(
                    PatientConnectedApp.patient_id
                    == current_patient.patient_id
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
