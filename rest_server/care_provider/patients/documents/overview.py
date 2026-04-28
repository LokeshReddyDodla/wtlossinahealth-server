"""Care-provider read of the cross-document patient overview.

Returns the same shape as the patient-facing overview endpoint so both
audiences see one source of truth — recomputed automatically by the
`rebuild_patient_documents_overview` arq task whenever any document is
added or deleted from either side.
"""

from fastapi import Depends, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_patient_documents_overview_service,
)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.profile_agent_documents import OverviewResponse
from lib.services.patient_documents_overview import PatientDocumentsOverviewService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get(
    "/overview",
    response_model=SuccessResponse[OverviewResponse],
    summary="Cross-document overview for a patient",
)
async def get_patient_documents_overview(
    patient_id: str,
    overview_service: PatientDocumentsOverviewService = Depends(
        get_patient_documents_overview_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ, CareProviderFeature.REPORTS
        )
    ),
):
    result = await overview_service.fetch(patient_id)
    if result is None:
        raise_http_exception(
            status_code=status.HTTP_404_NOT_FOUND,
            message="Overview not generated yet",
        )
    return SuccessResponse(data=result, message="Patient documents overview")
