from typing import Optional

from fastapi import Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (
    get_prescription_service,
)
from lib.models.patient import Patient
from lib.schemas.patient_prescription import PatientPrescriptionRead
from lib.services.prescription_service import PrescriptionService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import InQueueResponse, SuccessResponse

from .router import router


@router.get(
    path="",
    response_model=SuccessResponse,
)
async def get_prescriptions_api(
    request: Request,
    source: Optional[str] = Query(None),
    analyzed: Optional[str] = Query(None, regex="^(true|false|both)$"),
    order: Optional[str] = Query("desc"),
    limit: Optional[int] = Query(None),
    offset: int = Query(0, ge=0),
    prescription_service: PrescriptionService = Depends(
        get_prescription_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    """
    Get Prescriptions API
    """
    try:
        prescriptions = await prescription_service.fetch_prescriptions(
            patient_id=str(current_patient.patient_id),
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
            message="Prescriptions fetched successfully",
            data=prescriptions,
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get("/{prescription_id}", response_model=SuccessResponse)
async def get_prescription_by_id(
    prescription_id: str,
    prescription_service: PrescriptionService = Depends(
        get_prescription_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        prescription = await prescription_service.fetch_prescription(
            prescription_id
        )
        data = PatientPrescriptionRead.from_orm(prescription)
        return SuccessResponse(
            message="Prescription fetched successfully",
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
