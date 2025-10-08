from typing import Optional

from fastapi import Body, Depends, HTTPException, Query, Request, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (
    get_prescription_analysis_service,
    get_prescription_service,
)
from lib.schemas.patient_prescription_analysis import (
    PrescriptionStructureResponse,
)
from lib.services.prescription_analysis_service import (
    PrescriptionAnalysisService,
)
from lib.services.prescription_service import PrescriptionService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import InQueueResponse, SuccessResponse
from lib.models.care_provider import CareProvider as CareProviderModel

from .router import router


@router.post(
    path="/preview",
    response_model=SuccessResponse,
)
async def preview_patient_prescriptions(
    request: Request,
    patient_id: str,
    image_url: str = Body(..., embed=True),
    prescription_analysis_service: PrescriptionAnalysisService = Depends(
        get_prescription_analysis_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ,
            CareProviderFeature.REPORTS,
        )
    ),
):

    try:
        parsed_ai_response = (
            await prescription_analysis_service.analyze_prescription_structure(
                image_url=image_url,
                user_id=patient_id,
                user_type=ProfileTypeEnum.PATIENT,
            )
        )

        if not parsed_ai_response:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Failed to analyze the prescription. Please try again or upload a clearer image.",
            )

        return SuccessResponse(
            message="Prescription preview generated successfully",
            data=parsed_ai_response,
        )

    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.post(
    path="/confirm",
    response_model=SuccessResponse,
)
async def summary_patient_prescriptions(
    request: Request,
    patient_id: str,
    confirmed_prescription: PrescriptionStructureResponse,
    prescription_service: PrescriptionService = Depends(
        get_prescription_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ,
            CareProviderFeature.REPORTS,
        )
    ),
):
    try:
        saved_prescription = (
            await prescription_service.confirm_prescription_analysis(
                patient_id=patient_id,
                confirmed_prescription=confirmed_prescription,
            )  # type: ignore
        )

        return SuccessResponse(
            message="Prescription summary generated and confirmed successfully",
            data={"conversation_id": saved_prescription.prescription_id},
        )

    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
