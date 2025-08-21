from typing import Literal, Optional
from fastapi import Depends, HTTPException, Query, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_care_provider_profile_service,
    get_package_service,
    get_patient_package_assignment_service,
)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.models.patient_package_assignment import AssignmentStatus
from lib.schemas.patient import Patient as PatientSchema

from lib.schemas.patient_package_assignment import (
    PatientPackageAssignmentWithDetail,
)
from lib.services.package_service import PackageService
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


@router.get("/{package_id}/patients", response_model=SuccessResponse)
async def get_patients_of_package(
    package_id: str,
    package_status: Optional[Literal["active", "inactive"]] = Query(
        None,
        description="Filter patients by assignment status; if not provided, returns all patients",
    ),
    package_service: PackageService = Depends(get_package_service),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ,
            CareProviderFeature.PACKAGES,
        )
    ),
):
    try:
        # Validate the care provider has a health facility
        if not current_care_provider.health_facility_id:  # type: ignore
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="No health facility associated with the care provider.",
            )

        # Fetch the package with detailed loading
        package = await package_service.fetch_package(
            package_id=package_id,
            detailed=True,
        )

        if status == "active":
            filtered_assignments = [
                a
                for a in package.patient_assignments
                if a.status == AssignmentStatus.ACTIVE
            ]
        elif status == "inactive":
            filtered_assignments = [
                a
                for a in package.patient_assignments
                if a.status != AssignmentStatus.ACTIVE
            ]
        else:
            filtered_assignments = package.patient_assignments

        # Extract and return only active patients

        patients_data = [
            {
                "assignment_id": str(a.assignment_id),
                "start_date": a.start_date,
                "end_date": a.end_date,
                "status": a.status,
                "patient": PatientSchema.from_orm(a.patient).model_dump(),
            }
            for a in filtered_assignments
        ]

        return SuccessResponse(
            message="Patients of the package fetched successfully.",
            data=patients_data,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get("/patients/{patient_id}/packages", response_model=SuccessResponse)
async def get_patient_assignments(
    patient_id: str,
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

        assignments = await patient_package_assignment_service.get_assignments_for_patient(
            patient_id=patient_id,
            health_facility_id=str(health_facility_id),
        )

        return SuccessResponse(
            message="Package assignments fetched successfully",
            data=[
                PatientPackageAssignmentWithDetail.from_orm(a)
                for a in assignments
            ],
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
