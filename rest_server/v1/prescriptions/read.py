"""GET /prescriptions/{patient_id} — list and detail endpoints."""

from datetime import date
from uuid import UUID

from fastapi import Depends, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_medication_service,
)
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.schemas.medication import MedicationResponse, PrescriptionResponse
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.medication_service import MedicationService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get(
    "/{patient_id}",
    response_model=SuccessResponse,
)
async def list_prescriptions(
    patient_id: str,
    medication_service: MedicationService = Depends(get_medication_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.PATIENT,
            ],
            care_provider_feature=CareProviderFeature.REPORTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """List all prescriptions for a patient."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )

    prescriptions = await medication_service.get_patient_prescriptions(
        patient_id=str(verified_pid),
    )

    today = date.today()
    data = [
        PrescriptionResponse(
            prescription_id=str(p.prescription_id),
            doctor_name=p.doctor_name,
            prescription_date=p.prescription_date,
            diagnosis=p.diagnosis or [],
            advice=p.advice or [],
            file_urls=p.file_urls or [],
            status=p.status,
            extracted_data=p.extracted_data,
            uploaded_by_id=str(p.uploaded_by_id) if p.uploaded_by_id else None,
            uploaded_by_type=p.uploaded_by_type,
            follow_up_required=p.follow_up_required,
            follow_up_date=p.follow_up_date,
            notes=p.notes,
            medications=[
                MedicationService.to_response(m, today)
                for m in (p.medications or [])
            ],
            created_at=p.created_at,
        ).model_dump(mode="json")
        for p in prescriptions
    ]

    return SuccessResponse(
        message="Prescriptions retrieved",
        data=data,
    )


@router.get(
    "/{patient_id}/{prescription_id}",
    response_model=SuccessResponse,
)
async def get_prescription(
    patient_id: str,
    prescription_id: str,
    medication_service: MedicationService = Depends(get_medication_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.PATIENT,
            ],
            care_provider_feature=CareProviderFeature.REPORTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Get a single prescription with its medications."""
    verified_pid = await resolve_patient_access(
        actor=current_actor,
        patient_id=UUID(patient_id),
        care_provider_access_service=care_provider_access_service,
    )

    prescription = await medication_service.get_prescription(
        prescription_id=prescription_id,
        patient_id=str(verified_pid),
    )

    if not prescription:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND,
            message="Prescription not found",
        )

    today = date.today()
    data = PrescriptionResponse(
        prescription_id=str(prescription.prescription_id),
        doctor_name=prescription.doctor_name,
        prescription_date=prescription.prescription_date,
        diagnosis=prescription.diagnosis or [],
        advice=prescription.advice or [],
        file_urls=prescription.file_urls or [],
        status=prescription.status,
        extracted_data=prescription.extracted_data,
        uploaded_by_id=str(prescription.uploaded_by_id) if prescription.uploaded_by_id else None,
        uploaded_by_type=prescription.uploaded_by_type,
        follow_up_required=prescription.follow_up_required,
        follow_up_date=prescription.follow_up_date,
        notes=prescription.notes,
        medications=[
            MedicationService.to_response(m, today)
            for m in (prescription.medications or [])
        ],
        created_at=prescription.created_at,
    ).model_dump(mode="json")

    return SuccessResponse(
        message="Prescription retrieved",
        data=data,
    )
