from typing import Optional

from fastapi import Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (
    get_prescription_service,
)
from lib.models.patient import Patient
from lib.schemas.patient_prescription import PatientPrescriptionRead
from lib.services.prescription_service import PrescriptionServiceLegacy as PrescriptionService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import InQueueResponse, SuccessResponse
from lib.models.care_provider import CareProvider as CareProviderModel

from .router import router


@router.get(
    path="",
    response_model=SuccessResponse,
)
async def get_patient_prescriptions(
    request: Request,
    patient_id: str,
    source: Optional[str] = Query(None),
    analyzed: Optional[str] = Query(None, regex="^(true|false|both)$"),
    order: Optional[str] = Query("desc"),
    limit: Optional[int] = Query(None),
    offset: int = Query(0, ge=0),
    prescription_service: PrescriptionService = Depends(
        get_prescription_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ, CareProviderFeature.REPORTS
        )
    ),
):
    try:
        prescriptions = await prescription_service.fetch_prescriptions(
            patient_id=patient_id,
            source=source,
            analyzed=analyzed,
            order=order,
            limit=limit,
            offset=offset,
        )

        prescriptions = [
            PatientPrescriptionRead.from_orm(prescription)
            for prescription in prescriptions
        ]

        return SuccessResponse(
            message="Patient prescriptions fetched successfully",
            data=prescriptions,
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get("/{prescription_id}", response_model=SuccessResponse)
async def get_patient_prescription_by_id(
    prescription_id: str,
    prescription_service: PrescriptionService = Depends(
        get_prescription_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ, CareProviderFeature.REPORTS
        )
    ),
):
    try:
        prescription = await prescription_service.fetch_prescription(
            prescription_id
        )
        data = PatientPrescriptionRead.from_orm(prescription)
        return SuccessResponse(
            message="Patient prescription fetched successfully",
            data=data,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
