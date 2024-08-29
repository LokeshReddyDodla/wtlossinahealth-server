from fastapi import APIRouter, HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient

from lib.models.patient import Patient
from sqlalchemy.future import select
from lib.models.patient_connected_app import (
    PatientConnectedApp,
    PatientLibreView,
)
from lib.schemas.patient_connected_app import (
    PatientLibreViewCreate,
    PatientLibreView as PatientLibreViewSchema,
)
from rest_server.patients.connected_apps.api_schema import AddLibreViewResponse
from rest_server.response_models import SuccessResponse, ErrorResponse
from typing import Union
from sqlalchemy.orm import selectinload
from .router import router


@router.post(
    "/add-libreview",
    tags=["ConnectedApps"],
    response_model=AddLibreViewResponse,
)
async def add_libreview(
    request: Request,
    libreview: PatientLibreViewCreate,
    current_patient: Patient = Depends(get_current_patient),
) -> Union[AddLibreViewResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            connected_app = await session.execute(
                select(PatientConnectedApp).where(
                    PatientConnectedApp.patient_id
                    == current_patient.patient_id
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
