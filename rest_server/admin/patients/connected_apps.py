from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import Session, selectinload

from lib.dependencies.auth.admin_auth import get_current_admin
from lib.dependencies.database import get_postgres_session
from lib.models.admin import Admin
from lib.models.patient_connected_app import PatientConnectedApp
from rest_server.response_models import ErrorResponse, SuccessResponse

router = APIRouter(prefix="/admin/patient")


@router.get(
    "/connected-apps/libreview",
    tags=["Admin Patient"],
    response_model=SuccessResponse,
)
async def get_libreview_connected_patients(
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
    current_admin: Admin = Depends(get_current_admin),
) -> Union[SuccessResponse, HTTPException]:
    try:
        result = await session.execute(
            select(PatientConnectedApp)
            .where(PatientConnectedApp.libreview != None)
            .options(
                selectinload(PatientConnectedApp.libreview),
                selectinload(PatientConnectedApp.patient),
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
