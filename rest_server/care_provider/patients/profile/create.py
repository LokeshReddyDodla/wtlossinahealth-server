from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import get_patient_profile_service
from lib.models.patient import Patient
from lib.schemas.patient import Patient as PatientSchema
from lib.schemas.patient import PatientCreate
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse
from lib.models.care_provider import CareProvider as CareProviderModel

from .router import router


@router.post(path="/profile", response_model=SuccessResponse)
async def create_patient(
    request: Request,
    patient_data: PatientCreate,
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.CREATE, CareProviderFeature.PATIENTS
        )
    ),
):
    try:
        new_patient = await patient_profile_service.create_patient(
            patient_data=patient_data,
            creating_care_provider=current_care_provider,
        )  # type: ignore
        result = PatientSchema.from_orm(new_patient)

        return SuccessResponse(
            message="Patient created and assigned to care provider",
            data=result,
        )

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
