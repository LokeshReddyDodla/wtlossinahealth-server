from typing import List, Optional
from fastapi import Depends, HTTPException, Query, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import (
    get_care_provider_profile_service,
    get_cgm_report_service,
    get_chat_management_service,
    get_patient_profile_service,
    get_user_device_service,
)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.patient import CompletePatientProfile
from lib.services.care_provider_profile_service import (
    CareProviderProfileService,
)
from lib.services.cgm_report_service import CGMReportService
from lib.services.chat.chat_management_service import ChatManagementService
from lib.services.patient_profile_service import PatientProfileService
from lib.services.user_device_service import UserDeviceService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.care_provider.patients.profile.api_schema import (
    CareProviderPatients,
)
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("", response_model=SuccessResponse)
async def list_patients(
    search: Optional[str] = Query(None),
    age: Optional[List[str]] = Query(None),
    gender: Optional[List[str]] = Query(None),
    monitoringMethod: Optional[List[str]] = Query(None),
    connectedApps: Optional[List[str]] = Query(None),
    package: Optional[List[str]] = Query(None),
    care_provider_profile_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
    cgm_report_service: CGMReportService = Depends(get_cgm_report_service),
    user_device_service: UserDeviceService = Depends(get_user_device_service),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ, CareProviderFeature.PATIENTS
        )
    ),
):
    try:
        patients = (
            await care_provider_profile_service.fetch_care_provider_patients(
                str(current_care_provider.care_provider_id),
                str(current_care_provider.role).lower(),
                str(current_care_provider.health_facility_id),
                search=search,
                age=age,
                gender=gender,
                monitoringMethod=monitoringMethod,
                package=package,
                connected_apps=connectedApps,
            )
        )

        if monitoringMethod and "cgm" in monitoringMethod:
            filtered_patients = []
            for patient in patients:
                cgm_reports = await cgm_report_service.fetch_reports(
                    str(patient.patient_id)
                )
                if cgm_reports:
                    filtered_patients.append(patient)
            patients = filtered_patients

        user_ids = [str(p.patient_id) for p in patients]
        last_active_map = await user_device_service.get_last_active_map(
            user_ids=user_ids,
            profile_type=ProfileTypeEnum.PATIENT.value,
        )

        updated_patients = []

        for patient in patients:
            cgm_reports = await cgm_report_service.fetch_reports(
                str(patient.patient_id)
            )
            updated_patient = {
                **CareProviderPatients.from_orm(patient).model_dump(),
                "reports": {"cgm": cgm_reports},
                "last_active_at": last_active_map.get(str(patient.patient_id)),
            }
            updated_patients.append(updated_patient)

        return SuccessResponse(
            message="Patients fetched successfully",
            data=updated_patients,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get("/{patient_id}", response_model=SuccessResponse)
async def get_patient_profile(
    patient_id: str,
    detailed: bool = False,
    include_health_data: bool = False,
    other_related_data: bool = False,
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
    user_device_service: UserDeviceService = Depends(get_user_device_service),
    chat_management_service: ChatManagementService = Depends(
        get_chat_management_service
    ),
    cgm_report_service: CGMReportService = Depends(get_cgm_report_service),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ, CareProviderFeature.PATIENTS
        )
    ),
):
    try:
        profile = await patient_profile_service.fetch_patient_profile(
            patient_id,
            detailed=detailed,
            include_health_data=include_health_data,
            other_related_data=other_related_data,
        )

        direct_chat = await chat_management_service.find_direct_chat(
            patient_id, str(current_care_provider.care_provider_id)
        )

        cgm_reports = await cgm_report_service.fetch_reports(patient_id)

        last_active_at = await user_device_service.get_user_last_active_at(
            user_id=patient_id,
            profile_type=ProfileTypeEnum.PATIENT.value,
        )

        return SuccessResponse(
            message="Patient profile fetched successfully",
            data={
                **CompletePatientProfile.from_orm(profile).model_dump(),
                "direct_chat_id": direct_chat,
                "reports": {"cgm": cgm_reports},
                "last_active_at": last_active_at,
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
