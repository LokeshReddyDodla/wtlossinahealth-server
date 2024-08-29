from fastapi import APIRouter, HTTPException, Request, Depends
from lib.dependencies.auth.patient_auth import get_current_patient

from lib.models.patient import Patient
from sqlalchemy.future import select
from lib.models.patient_connected_app import (
    PatientConnectedApp,
    PatientOtherApp,
)
from lib.schemas.patient_connected_app import (
    PatientOtherAppCreate,
    PatientOtherApp as PatientOtherAppSchema,
)
from rest_server.patients.connected_apps.api_schema import AddOtherAppResponse
from rest_server.response_models import SuccessResponse, ErrorResponse
from typing import Union
from sqlalchemy.orm import selectinload
from .router import router


@router.post(
    "/add-other-app",
    response_model=AddOtherAppResponse,
)
async def add_other_app(
    request: Request,
    other_app: PatientOtherAppCreate,
    current_patient: Patient = Depends(get_current_patient),
) -> Union[AddOtherAppResponse, HTTPException]:
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

            new_other_app = PatientOtherApp(
                connected_app_id=connected_app.id,
                other_app_id=other_app.other_app_id,
                additional_field=other_app.additional_field,
            )
            session.add(new_other_app)
            await session.commit()
            await session.refresh(new_other_app)

            result = PatientOtherAppSchema.from_orm(new_other_app)

            return AddOtherAppResponse(
                message="OtherApp data added successfully.",
                data=result,
            )
        except Exception as e:
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())
