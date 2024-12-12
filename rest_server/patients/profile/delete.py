from typing import List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_patient_profile_service
from lib.models.patient import Patient
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.delete(path="/delete", response_model=SuccessResponse)
async def delete_patient_api(
    request: Request,
    delete_chats: Optional[bool] = True,
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        await patient_profile_service.delete_patient_profile(
            patient_id=str(current_patient.patient_id), delete_chats=True
        )

        return SuccessResponse(message="Patient deleted successfully.")
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
