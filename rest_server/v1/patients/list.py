from typing import Optional

from fastapi import Depends, HTTPException, Query, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import get_cgm_report_service, get_patient_profile_service, get_user_device_service
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.schemas.health_facility import HealthFacility as HealthFacilitySchema
from lib.schemas.package import Package as PackageSchema
from lib.schemas.patient import Patient as PatientSchema
from lib.services.cgm_report_service import CGMReportService
from lib.services.patient_profile_service import PatientProfileService
from lib.services.user_device_service import UserDeviceService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse
from rest_server.v1.utils import (
    get_effective_health_facility_id,
    get_effective_care_provider_id,
)

from .router import router


@router.get("", response_model=SuccessResponse)
async def list_patients(
    limit: Optional[int] = Query(None, description="Limit number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    patient_service: PatientProfileService = Depends(get_patient_profile_service),
    user_device_service: UserDeviceService = Depends(get_user_device_service),
    cgm_report_service: CGMReportService = Depends(get_cgm_report_service),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
            ],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
):
    try:
        effective_health_facility_id = get_effective_health_facility_id(
            current_actor=current_actor,
        )
        effective_care_provider_id = get_effective_care_provider_id(
            current_actor=current_actor,
        )

        patients = await patient_service.fetch_patients(
            health_facility_id=effective_health_facility_id,
            care_provider_id=effective_care_provider_id,
            limit=limit,
            offset=offset,
        )

        total = await patient_service.count_patients(
            health_facility_id=effective_health_facility_id,
            care_provider_id=effective_care_provider_id,
        )

        user_ids = [str(p.patient_id) for p in patients]
        last_active_map = await user_device_service.get_last_active_map(
            user_ids=user_ids,
            profile_type=ProfileTypeEnum.PATIENT.value,
        )

        response_data = []
        for patient in patients:
            patient_dict = PatientSchema.from_orm(patient).model_dump()
            
            # Add health facility if available
            if patient.health_facility:
                patient_dict["health_facility"] = HealthFacilitySchema.from_orm(
                    patient.health_facility
                ).model_dump()
            
            # Add care providers if available
            if patient.care_providers:
                patient_dict["care_providers"] = [
                    CareProviderSchema.from_orm(cp).model_dump()
                    for cp in patient.care_providers
                ]
            
            # Add packages from package_assignments if available
            if patient.package_assignments:
                patient_dict["packages"] = [
                    {
                        "package": PackageSchema.from_orm(assignment.package).model_dump()
                        if assignment.package else None,
                        "assignment_id": str(assignment.assignment_id),
                        "start_date": assignment.start_date,
                        "end_date": assignment.end_date,
                        "status": assignment.status,
                    }
                    for assignment in patient.package_assignments
                    if assignment.package
                ]
                
            # Add CGM reports
            cgm_reports = await cgm_report_service.fetch_reports(
                str(patient.patient_id)
            )
            patient_dict["reports"] = {"cgm": cgm_reports}
            
            # Add last active at
            patient_dict["last_active_at"] = last_active_map.get(str(patient.patient_id))


            response_data.append(patient_dict)

        return SuccessResponse(
            version="v1",
            message="Patients fetched successfully.",
            data={
                "total": total,
                "items": response_data,
            },
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )

