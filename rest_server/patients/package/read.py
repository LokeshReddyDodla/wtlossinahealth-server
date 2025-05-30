import traceback

from fastapi import Depends, HTTPException, Request, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.service_dependencies import (
    get_patient_package_assignment_service,
    get_patient_profile_service,
)
from lib.models.patient import Patient
from lib.schemas.package import Package
from lib.schemas.patient_package_assignment import (
    PatientPackageAssignmentWithDetail,
)
from lib.services.patient_package_assignment_service import (
    PatientPackageAssignmentService,
)
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get(path="", response_model=SuccessResponse)
async def get_patient_packages_api(
    request: Request,
    patient_package_assignment_service: PatientPackageAssignmentService = Depends(
        get_patient_package_assignment_service
    ),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        assignments = await patient_package_assignment_service.get_assignments_for_patient(
            patient_id=str(current_patient.patient_id),
            health_facility_id=str(current_patient.health_facility_id),
        )

        return SuccessResponse(
            message="Patient package fetched successfully",
            data=[
                PatientPackageAssignmentWithDetail.from_orm(a)
                for a in assignments
            ],
        )

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
