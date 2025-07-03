from datetime import date

from fastapi import Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import get_fitness_report_service
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.services.fitness_report_service import FitnessReportService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import InQueueResponse, SuccessResponse

from .router import router


@router.get("/report/day")
async def get_day_fitness_report(
    request: Request,
    patient_id: str = Query(...),
    date: date = Query(...),
    regenerate: bool = Query(False),
    fitness_report_service: FitnessReportService = Depends(
        get_fitness_report_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ, CareProviderFeature.REPORTS
        )
    ),
):
    try:
        fitness_report = await fitness_report_service.fetch_daily_report(
            str(patient_id), date, regenerate=regenerate
        )

        if not fitness_report:
            return InQueueResponse(
                message="Report is being generated. Please check back shortly.",
            )

        return SuccessResponse(
            message="Day Fitness report fetched successfully",
            data=fitness_report,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
