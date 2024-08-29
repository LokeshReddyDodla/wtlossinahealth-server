from typing import Union
from fastapi import APIRouter, Depends, HTTPException, Request
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient
from lib.models.patient_permission import PatientPermission
from lib.schemas.patient_permission import (
    PatientPermission as PatientPermissionSchema,
)
from sqlalchemy.future import select

from rest_server.patients.permissions.api_schema import (
    PatientPermissionsResponse,
)
from rest_server.response_models import ErrorResponse, SuccessResponse
from sqlalchemy.orm import selectinload
from .router import router


@router.get(
    path="", tags=["Permissions"], response_model=PatientPermissionsResponse
)
async def get_patient_permissions(
    request: Request, current_patient: Patient = Depends(get_current_patient)
) -> Union[PatientPermissionsResponse, HTTPException]:
    async with request.state.context.postgres_store.get_session() as session:
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
