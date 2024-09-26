from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.database import get_postgres_session
from lib.models.patient import Patient
from lib.models.patient_permission import PatientPermission
from lib.schemas.patient_permission import \
    PatientPermission as PatientPermissionSchema
from rest_server.patients.permissions.api_schema import \
    PatientPermissionsResponse
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.get(path="", response_model=PatientPermissionsResponse)
async def get_patient_permissions(
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
    current_patient: Patient = Depends(get_current_patient),
) -> Union[PatientPermissionsResponse, HTTPException]:
    try:
        result = await session.execute(
            select(PatientPermission).where(
                PatientPermission.patient_id == current_patient.patient_id
            )
        )

        permissions = result.scalars().first()
        if permissions is None:
            raise HTTPException(
                status_code=404, detail="Permissions not found"
            )

        result = PatientPermissionSchema.from_orm(permissions)

        return PatientPermissionsResponse(
            message="Permissions fetched successfully.",
            data=result,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())
