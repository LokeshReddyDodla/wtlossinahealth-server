from datetime import date

from fastapi import Depends, Request, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import get_token_usage_service
from lib.models.patient import Patient
from lib.services.token_usage_service import TokenUsageService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("", response_model=SuccessResponse)
async def get_patient_token_usage(
    request: Request,
    start_date: date,
    end_date: date,
    token_usage_service: TokenUsageService = Depends(get_token_usage_service),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        token_usage = await token_usage_service.get_usage_summary(
            user_id=str(current_patient.patient_id),
            user_type=ProfileTypeEnum.PATIENT,
            start_date=start_date,
            end_date=end_date,
        )

        return SuccessResponse(
            message="Token usage fetched successfully.",
            data=token_usage,
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
