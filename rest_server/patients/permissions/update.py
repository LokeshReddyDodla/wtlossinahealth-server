from typing import Union
from fastapi import APIRouter, Depends, HTTPException, Request
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient
from lib.models.patient_permission import PatientPermission
from lib.schemas.patient_permission import (
    PatientPermissionCreate,
    PatientPermissionUpdate,
)
from sqlalchemy.future import select

from rest_server.response_models import ErrorResponse, SuccessResponse
from sqlalchemy.orm import selectinload
from .router import router


@router.post("/sync", tags=["Patient"], response_model=SuccessResponse)
async def sync_permissions(
    request: Request,
    permissions: PatientPermissionUpdate,
    current_patient: Patient = Depends(get_current_patient),
) -> Union[SuccessResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
        try:
            result = await session.execute(
                select(Patient)
                .where(Patient.patient_id == current_patient.patient_id)
                .options(
                    selectinload(Patient.permissions),
                )
            )

            patient = result.scalars().first()
            if patient is None:
                raise HTTPException(
                    status_code=404, detail="Patient not found"
                )

            patient.permissions.notification_permission = (
                permissions.notification_permission
            )
            patient.permissions.health_permission = (
                permissions.health_permission
            )
            patient.permissions.camera_permission = (
                permissions.camera_permission
            )
            patient.permissions.storage_permission = (
                permissions.storage_permission
            )

            await session.commit()
            return SuccessResponse(message="Permissions synced successfully.")
        except HTTPException as http_exc:
            raise http_exc
        except Exception as e:
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=500, detail=response.dict())
