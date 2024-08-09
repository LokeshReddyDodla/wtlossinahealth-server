from fastapi import APIRouter, Depends, HTTPException, Request
from lib.dependencies.auth.admin_auth import get_current_admin
from lib.models.admin import Admin
from lib.models.patient_connected_app import PatientConnectedApp
from sqlalchemy.future import select
from sqlalchemy.orm import Session
from rest_server.response_models import SuccessResponse, ErrorResponse
from typing import Union
from sqlalchemy.orm import selectinload


router = APIRouter(prefix="/admin/patient")


@router.get(
    "/connected-apps/libreview", tags=["Admin"], response_model=SuccessResponse
)
async def get_libreview_connected_patients(
    request: Request, current_admin: Admin = Depends(get_current_admin)
) -> Union[SuccessResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
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
