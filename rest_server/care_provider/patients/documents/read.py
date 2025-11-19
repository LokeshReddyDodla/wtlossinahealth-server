import traceback
from datetime import date, datetime
from typing import Optional

from fastapi import Depends, HTTPException, Query, Request, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_cgm_report_service,
    get_fitness_stats_processor,
    get_meal_report_service,
    get_patient_document_service,
    get_patient_profile_service,
)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.patient import CorePatientProfile
from lib.schemas.patient_report import PatientReport
from lib.services.cgm_report_service import CGMReportService
from lib.services.meal_report_service import MealReportService
from lib.services.patient_document_service import PatientDocumentService
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.fitness.processor import FitnessStatsProcessor
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("")
async def get_patient_documents(
    request: Request,
    patient_id: str,
    document_type: Optional[str] = Query(
        None, description="Filter by document type"
    ),
    uploaded_by_type: Optional[str] = Query(
        None, description="Filter by uploader type (patient or care provider)"
    ),
    order: Optional[str] = Query(
        "asc", description="asc or desc by creation date"
    ),
    limit: Optional[int] = Query(20, description="Limit number of results"),
    offset: int = Query(0, description="Offset for pagination"),
    patient_document_service: PatientDocumentService = Depends(
        get_patient_document_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ, CareProviderFeature.REPORTS
        )
    ),
):
    try:
        documents = await patient_document_service.fetch_patient_documents(
            patient_id=patient_id,
            document_type=document_type,
            uploaded_by_type=uploaded_by_type,
            order=order,
            limit=limit,
            offset=offset,
        )

        return SuccessResponse(
            message="Patient documents fetched successfully",
            data=documents,
        )

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
