from fastapi import Depends, HTTPException, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_patient_package_assignment_service,
)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.patient_package_assignment import (
    PatientPackageAssignmentCreate,
)
from lib.services.patient_package_assignment_service import (
    PatientPackageAssignmentService,
)
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.delete("", response_model=SuccessResponse)
async def delete_package_assignment(
    assignment_id: str,
    patient_package_assignment_service: PatientPackageAssignmentService = Depends(
        get_patient_package_assignment_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.UPDATE,
            CareProviderFeature.PATIENTS,
        )
    ),
):
    try:
        health_facility_id = current_care_provider.health_facility_id

        if not health_facility_id:  # type: ignore
            raise_http_exception(
                status_code=status.HTTP_403_FORBIDDEN,
                message="Care provider is not associated with any health facility.",
            )

        await patient_package_assignment_service.remove_assignment(
            assignment_id=assignment_id,
            health_facility_id=str(current_care_provider.health_facility_id),
        )

        return SuccessResponse(
            message="Package assignment removed successfully",
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
