import uuid

from fastapi import Depends, HTTPException, Request, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import get_prescription_service
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.services.prescription_service import PrescriptionServiceLegacy as PrescriptionService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.delete(path="/{prescription_id}", response_model=SuccessResponse)
async def delete_patient_prescription(
    request: Request,
    patient_id: str,
    prescription_id: uuid.UUID,
    prescription_service: PrescriptionService = Depends(
        get_prescription_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.DELETE, CareProviderFeature.REPORTS
        )
    ),
):
    try:
        await prescription_service.delete_prescription(
            prescription_id=prescription_id, patient_id=patient_id
        )

        return SuccessResponse(
            message="Patient prescription deleted successfully."
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
