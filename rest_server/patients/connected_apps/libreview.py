from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.models.patient import Patient
from lib.models.patient_connected_app import (PatientConnectedApp,
                                              PatientLibreView)
from lib.schemas.patient_connected_app import \
    PatientLibreView as PatientLibreViewSchema
from lib.schemas.patient_connected_app import PatientLibreViewCreate
from rest_server.patients.connected_apps.api_schema import AddLibreViewResponse
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post(
    "/add-libreview",
    response_model=AddLibreViewResponse,
)
async def add_libreview(
    request: Request,
    libreview: PatientLibreViewCreate,
    session: AsyncSession = Depends(get_postgres_session),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        connected_app = await session.execute(
            select(PatientConnectedApp).where(
                PatientConnectedApp.patient_id == current_patient.patient_id
            )
        )
        connected_app = connected_app.scalars().first()

        if not connected_app:
            raise HTTPException(
                status_code=404, detail="ConnectedApp instance not found"
            )

        new_libreview = PatientLibreView(
            connected_app_id=connected_app.id,
            libreview_id=libreview.libreview_id,
            last_sync_timestamp=libreview.last_sync_timestamp,
        )
        session.add(new_libreview)
        await session.commit()
        await session.refresh(new_libreview)

        result = PatientLibreViewSchema.from_orm(new_libreview)

        return AddLibreViewResponse(
            message="LibreView data added successfully.",
            data=result,
        )
    except Exception as e:
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())
