from datetime import datetime
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
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
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("", response_model=SuccessResponse)
async def list_patient_exports(
    patient_id: str | None = Query(None),
    statuses: list[str] | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    include_download_urls: bool = Query(False),
    export_service: PatientDataExportService = Depends(get_patient_data_export_service),
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
        parsed_patient_id = UUID(patient_id) if patient_id else None

        # Admin can view all, care provider sees only own requested exports here.
        requester_filter = (
            UUID(current_actor.id)
            if current_actor.role == ProfileTypeEnum.CARE_PROVIDER
            else None
        )

        exports = await export_service.list_exports(
            patient_id=parsed_patient_id,
            statuses=statuses,
            requester_id=requester_filter,
            limit=limit,
            offset=offset,
        )
        total = await export_service.count_exports(
            patient_id=parsed_patient_id,
            statuses=statuses,
            requester_id=requester_filter,
        )

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
            message="Export list fetched successfully",
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
            message="Failed to fetch export list",
            detail=str(e),
        )


@router.get("/{export_id}", response_model=SuccessResponse)
async def get_patient_export_status(
    export_id: str,
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
        export_uuid = UUID(export_id)
        export = await export_service.get_export_by_id(export_uuid)
        if not export:
            raise_http_exception(status_code=404, message="Export job not found")

        if current_actor.role == ProfileTypeEnum.CARE_PROVIDER:
            is_assigned = await care_provider_access_service.is_patient_assigned(
                care_provider_id=current_actor.model.care_provider_id,
                patient_id=export.patient_id,
            )
            is_requester = str(export.requester_id) == current_actor.id
            if not (is_assigned or is_requester):
                raise_http_exception(
                    status_code=status.HTTP_403_FORBIDDEN,
                    message="You do not have access to this export",
                )

        # Mark stale completed exports as expired on read.
        if (
            export.status == "completed"
            and export.expires_at is not None
            and export.expires_at < datetime.now().replace(tzinfo=None)
        ):
            export.status = "expired"
            await export_service.mark_expired(export_uuid)

        download_url = None
        if export.status == "completed":
            download_url = await export_service.generate_download_url(export)
            if download_url:
                await export_service.mark_downloaded(export_uuid)

        return SuccessResponse(
            message="Export status fetched successfully",
            data={
                "export_id": str(export.export_id),
                "patient_id": str(export.patient_id),
                "status": export.status,
                "progress": export.progress,
                "created_at": export.created_at,
                "completed_at": export.completed_at,
                "expires_at": export.expires_at,
                "checksum": export.checksum,
                "error": export.error,
                "download_url": download_url,
            },
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to fetch export status",
            detail=str(e),
        )
