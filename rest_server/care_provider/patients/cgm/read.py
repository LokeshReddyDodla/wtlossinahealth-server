from datetime import date, datetime, time

from fastapi import Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import get_glucose_stats_processor
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.utils.care_provider_permissions import (CareProviderFeature,
                                                 CareProviderPermissionAction)
from lib.utils.glucose.processor import GlucoseStatsProcessor
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/report/day")
async def get_cgm_day_report(
    request: Request,
    patient_id: str = Query(...),
    date: date = Query(...),
    glucose_stats_processor: GlucoseStatsProcessor = Depends(
        get_glucose_stats_processor
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ, CareProviderFeature.REPORTS
        )
    ),
):
    try:
        start_date = datetime.combine(date, time.min)  # Start of the day
        end_date = datetime.combine(date, time.max)  # End of the day

        glucose_stats = await glucose_stats_processor.generate_report(
            str(patient_id), start_date, end_date
        )

        return SuccessResponse(
            message="Day Glucose report fetched successfully",
            data=glucose_stats["day_wise"][0],
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
