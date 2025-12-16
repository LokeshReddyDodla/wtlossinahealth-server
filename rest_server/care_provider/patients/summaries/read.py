from typing import Optional
from fastapi import Depends, HTTPException, Query, status
from bson import ObjectId
from fastapi.encoders import jsonable_encoder

from lib.dependencies.auth.care_provider_auth import (
    CareProviderPermissionAction,
    CareProviderFeature,
    get_current_care_provider,
)
from lib.dependencies.service_dependencies import get_patient_summary_service
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.services.patient_summary_service import PatientSummaryService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/{patient_id}", response_model=SuccessResponse)
async def get_patient_summary(
    patient_id: str,
    period: str = Query(
        ...,
        description="Period name: YESTERDAY, THIS_WEEK, LAST_WEEK, THIS_MONTH, LAST_MONTH, LAST_30_DAYS, LAST_90_DAYS",
    ),
    patient_summary_service: PatientSummaryService = Depends(
        get_patient_summary_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ, CareProviderFeature.PATIENTS
        )
    ),
):
    try:
        # Validate period name
        valid_periods = [
            "YESTERDAY",
            "THIS_WEEK",
            "LAST_WEEK",
            "THIS_MONTH",
            "LAST_MONTH",
            "LAST_30_DAYS",
            "LAST_90_DAYS",
        ]
        if period.upper() not in valid_periods:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Invalid period name",
                detail=f"Period must be one of: {', '.join(valid_periods)}",
            )

        summary = await patient_summary_service.fetch_summary_by_period(
            patient_id=patient_id, period_name=period
        )

        if summary is None:
            return SuccessResponse(
                message=f"No summary found for period: {period}",
                data=None,
            )

        summary_dict = jsonable_encoder(
            summary, custom_encoder={ObjectId: str}
        )

        return SuccessResponse(
            message=f"Patient summary fetched successfully for period: {period}",
            data=summary_dict,
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Invalid period name",
            detail=str(e),
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to fetch patient summary",
            detail=str(e),
        )

