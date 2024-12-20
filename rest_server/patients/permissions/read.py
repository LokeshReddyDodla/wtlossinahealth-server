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
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.get(path="", response_model=SuccessResponse)
async def get_patient_permissions(
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        result = await session.execute(
            select(PatientPermission).where(
                PatientPermission.patient_id == current_patient.patient_id
            )
        )

        permissions = result.scalars().first()
        if permissions is None:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Permission not found.",
            )

        return SuccessResponse(
            message="Permissions fetched successfully.",
            data=PatientPermissionSchema.model_validate(permissions),
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
