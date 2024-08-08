from fastapi import APIRouter, HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient_connected_app import (
    LibreView,
    OtherApp,
    PatientConnectedApp,
)
from lib.models.patient import Patient
from lib.schemas.patient_connected_app import LibreViewCreate, OtherAppCreate
from sqlalchemy.future import select
from rest_server.response_models import SuccessResponse, ErrorResponse
from typing import Union
from sqlalchemy.orm import selectinload


router = APIRouter(prefix="/patient")


@router.post(
    "/connected-apps/libreview",
    tags=["ConnectedApps"],
    response_model=SuccessResponse,
)
async def add_libreview(
    request: Request,
    libreview: LibreViewCreate,
    current_patient: Patient = Depends(get_current_patient),
) -> Union[SuccessResponse, HTTPException]:
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

            new_libreview = LibreView(
                connected_app_id=connected_app.id,
                libreview_id=libreview.libreview_id,
                last_sync_timestamp=libreview.last_sync_timestamp,
            )
            session.add(new_libreview)
            await session.commit()
            await session.refresh(new_libreview)
            return SuccessResponse(
                message="LibreView data added successfully.",
                data=new_libreview,
            )
        except Exception as e:
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())


@router.post(
    "/connected-apps/other-app",
    tags=["ConnectedApps"],
    response_model=SuccessResponse,
)
async def add_other_app(
    request: Request,
    other_app: OtherAppCreate,
    current_patient: Patient = Depends(get_current_patient),
) -> Union[SuccessResponse, HTTPException]:
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

            new_other_app = OtherApp(
                connected_app_id=connected_app.id,
                other_app_id=other_app.other_app_id,
                additional_field=other_app.additional_field,
            )
            session.add(new_other_app)
            await session.commit()
            await session.refresh(new_other_app)
            return SuccessResponse(
                message="OtherApp data added successfully.",
                data=new_other_app,
            )
        except Exception as e:
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())


@router.get(
    "/connected-apps", tags=["ConnectedApps"], response_model=SuccessResponse
)
async def get_patient_connected_apps(
    request: Request, current_patient: Patient = Depends(get_current_patient)
) -> Union[SuccessResponse, HTTPException]:
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
            return SuccessResponse(
                message="Connected apps fetched successfully.",
                data=connected_apps,
            )
        except Exception as e:
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())
