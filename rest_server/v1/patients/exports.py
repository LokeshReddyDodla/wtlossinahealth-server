from uuid import UUID

from fastapi import Depends, HTTPException, Query, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_patient_data_export_service,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.patient_data_export_service import PatientDataExportService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from lib.workers.tasks.patient_export.enqueue import enqueue_patient_export_async
from rest_server.response_models import SuccessResponse

from .router import router


@router.post("/{patient_id}/exports", response_model=SuccessResponse)
async def request_patient_data_export(
    patient_id: str,
    export_service: PatientDataExportService = Depends(get_patient_data_export_service),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
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
        target_patient_id = await resolve_patient_access(
            actor=current_actor,
            patient_id=UUID(patient_id),
            care_provider_access_service=care_provider_access_service,
        )

        export = await export_service.create_export(
            patient_id=target_patient_id,
            requester_id=UUID(current_actor.id),
            requester_role=current_actor.role,
        )

        job_id = await enqueue_patient_export_async(str(export.export_id))
        if not job_id:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to enqueue export job",
            )

        return SuccessResponse(
            message="Patient export requested successfully",
            data={
                "export_id": str(export.export_id),
                "status": export.status,
                "job_id": job_id,
            },
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to request patient data export",
            detail=str(e),
        )


@router.get("/{patient_id}/exports", response_model=SuccessResponse)
async def list_exports_for_patient(
    patient_id: str,
    statuses: list[str] | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    include_download_urls: bool = Query(False),
    export_service: PatientDataExportService = Depends(get_patient_data_export_service),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
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
        target_patient_id = await resolve_patient_access(
            actor=current_actor,
            patient_id=UUID(patient_id),
            care_provider_access_service=care_provider_access_service,
        )

        exports = await export_service.list_exports(
            patient_id=target_patient_id,
            statuses=statuses,
            limit=limit,
            offset=offset,
        )
        total = await export_service.count_exports(
            patient_id=target_patient_id,
            statuses=statuses,
        )

        from datetime import datetime

        items = []
        for export in exports:
            download_url = None
            if (
                include_download_urls
                and export.status == "completed"
                and export.expires_at is not None
                and export.expires_at >= datetime.now().replace(tzinfo=None)
            ):
                download_url = await export_service.generate_download_url(export)

            items.append(
                {
                    "export_id": str(export.export_id),
                    "patient_id": str(export.patient_id),
                    "requester_id": str(export.requester_id),
                    "requester_role": export.requester_role,
                    "status": export.status,
                    "progress": export.progress,
                    "created_at": export.created_at,
                    "completed_at": export.completed_at,
                    "expires_at": export.expires_at,
                    "checksum": export.checksum,
                    "error": export.error,
                    "download_url": download_url,
                }
            )

        return SuccessResponse(
            message="Patient export history fetched successfully",
            data={
                "total": total,
                "items": items,
            },
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to fetch patient export history",
            detail=str(e),
        )
