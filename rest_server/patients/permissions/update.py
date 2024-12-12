from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.models.patient import Patient
from lib.models.patient_permission import PatientPermission
from lib.schemas.patient_permission import \
    PatientPermission as PatientPermissionSchema
from lib.schemas.patient_permission import (PatientPermissionCreate,
                                            PatientPermissionUpdate)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post("/sync", response_model=SuccessResponse)
async def sync_permissions(
    request: Request,
    permissions: PatientPermissionUpdate,
    session: AsyncSession = Depends(get_postgres_session),
    current_patient: Patient = Depends(get_current_patient),
):
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
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Patient not found",
            )

        patient.permissions.notification_permission = (
            permissions.notification_permission
        )
        patient.permissions.health_permission = permissions.health_permission
        patient.permissions.camera_permission = permissions.camera_permission
        patient.permissions.storage_permission = permissions.storage_permission

        await session.commit()

        return SuccessResponse(
            message="Permissions synced successfully.",
            data=PatientPermissionSchema.model_validate(patient.permissions),
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
