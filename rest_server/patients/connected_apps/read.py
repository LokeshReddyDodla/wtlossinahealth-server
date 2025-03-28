
from fastapi import Depends, HTTPException, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import \
    get_patient_connected_app_service
from lib.models.patient import Patient
from lib.schemas.patient_connected_app import \
    PatientConnectedApp as PatientConnectedAppSchema
from lib.services.patient_connected_app_service import \
    PatientConnectedAppService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("", response_model=SuccessResponse)
async def get_patient_connected_apps(
    request: Request,
    patient_connected_app_service: PatientConnectedAppService = Depends(
        get_patient_connected_app_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        connected_app = (
            await (
                patient_connected_app_service.get_connected_apps_for_patient(
                    str(current_patient.patient_id)
                )
            )
        )

        return SuccessResponse(
            message="Connected apps fetched successfully.",
            data=PatientConnectedAppSchema.from_orm(connected_app),
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
