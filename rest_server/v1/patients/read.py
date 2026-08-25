from uuid import UUID

from fastapi import Depends, HTTPException, Query, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_cgm_report_service,
    get_direct_chat_resolver,
    get_patient_profile_service,
    get_user_device_service,
)
from lib.schemas.patient import CompletePatientProfile
from lib.services import presence_service
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.reports import CGMReportService
from lib.services.chat.direct_chat_resolver import DirectChatResolver
from lib.services.patient_profile_service import PatientProfileService
from lib.services.user_device_service import UserDeviceService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/{patient_id}", response_model=SuccessResponse)
async def get_patient_profile(
    patient_id: str,
    detailed: bool = Query(False, description="Include detailed profile information"),
    include_health_data: bool = Query(
        False, description="Include health data in profile"
    ),
    other_related_data: bool = Query(
        False, description="Include other related data in profile"
    ),
    patient_profile_service: PatientProfileService = Depends(
        get_patient_profile_service
    ),
    user_device_service: UserDeviceService = Depends(get_user_device_service),
    cgm_report_service: CGMReportService = Depends(get_cgm_report_service),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
    direct_chat_resolver: DirectChatResolver = Depends(get_direct_chat_resolver),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.PATIENT,
            ],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
):
    try:
        # Resolve and validate patient access
        target_patient_id = await resolve_patient_access(
            actor=current_actor,
            patient_id=UUID(patient_id) if patient_id else None,
            care_provider_access_service=care_provider_access_service,
        )

        if not target_patient_id:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Patient not found",
            )

        # Fetch patient profile
        profile = await patient_profile_service.fetch_patient_profile(
            str(target_patient_id),
            detailed=detailed,
            include_health_data=include_health_data,
            other_related_data=other_related_data,
        )

        # Fetch CGM reports
        cgm_reports = await cgm_report_service.fetch_reports(str(target_patient_id))

        # Fetch last active time
        last_active_at = await user_device_service.get_user_last_active_at(
            user_id=str(target_patient_id),
            profile_type=ProfileTypeEnum.PATIENT.value,
        )

        # Build response data
        response_data = {
            **CompletePatientProfile.from_orm(profile).model_dump(),
            "reports": {"cgm": cgm_reports},
            "last_active_at": last_active_at,
            "online": await presence_service.is_online(str(target_patient_id)),
        }

        response_data["direct_chat_id"] = await direct_chat_resolver.resolve(
            actor=current_actor,
            patient_id=target_patient_id,
            care_providers=profile.care_providers,
        )

        return SuccessResponse(
            message="Patient profile fetched successfully",
            data=response_data,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
