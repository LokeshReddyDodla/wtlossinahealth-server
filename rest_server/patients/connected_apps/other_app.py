from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.models.patient import Patient
from lib.models.patient_connected_app import (PatientConnectedApp,
                                              PatientOtherApp)
from lib.schemas.patient_connected_app import \
    PatientOtherApp as PatientOtherAppSchema
from lib.schemas.patient_connected_app import PatientOtherAppCreate
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post(
    "/add-other-app",
    response_model=SuccessResponse,
)
async def add_other_app(
    request: Request,
    other_app: PatientOtherAppCreate,
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
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="ConnectedApp instance not found",
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

        return SuccessResponse(
            message="OtherApp data added successfully.",
            data=result,
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
