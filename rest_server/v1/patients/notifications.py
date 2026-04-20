"""V1 patient notification inbox endpoints."""

from typing import Optional
from uuid import UUID

from fastapi import Depends, Path, Query, status

from lib.core.constants import ProfileTypeEnum
from lib.core.types import NotificationCategoryLiteral
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.patient_access import resolve_patient_access
from lib.dependencies.service_dependencies import (
    get_care_provider_access_service,
    get_patient_notification_service,
)
from lib.schemas.patient_notification import (
    MarkReadResponse,
    NotificationListResponse,
    NotificationResponse,
)
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.notifications import PatientNotificationService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse

from .router import router

_ACTOR_DEPS = dict(
    allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER, ProfileTypeEnum.ADMIN],
    check_permissions=False,
)


def _to_response(
    notif,
    dose_status: Optional[str] = None,
) -> NotificationResponse:
    return NotificationResponse(
        id=str(notif.id),
        patient_id=str(notif.patient_id),
        category=notif.category,
        title=notif.title,
        body=notif.body,
        severity=notif.severity,
        deeplink=notif.deeplink,
        data=notif.data or {},
        dose_status=dose_status,
        read_at=notif.read_at,
        dismissed_at=notif.dismissed_at,
        created_at=notif.created_at,
    )


@router.get(
    "/{patient_id}/notifications",
    response_model=SuccessResponse,
)
async def list_notifications(
    patient_id: str = Path(...),
    unread_only: bool = Query(False),
    category: Optional[NotificationCategoryLiteral] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: PatientNotificationService = Depends(get_patient_notification_service),
    current_actor: Actor = Depends(get_current_actor(**_ACTOR_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    try:
        verified_pid = await resolve_patient_access(
            actor=current_actor,
            patient_id=UUID(patient_id),
            care_provider_access_service=care_provider_access_service,
        )
        rows, total, unread = await service.list_for_patient(
            str(verified_pid),
            unread_only=unread_only,
            category=category,
            limit=limit,
            offset=offset,
        )
        dose_statuses = await service.resolve_dose_statuses(rows)
        notifications = [
            _to_response(r, dose_status=dose_statuses.get(str(r.id))) for r in rows
        ]
        payload = NotificationListResponse(
            notifications=notifications,
            total=total,
            unread_count=unread,
            limit=limit,
            offset=offset,
        )
        return SuccessResponse(
            message=f"{len(notifications)} notifications fetched.",
            data=payload.model_dump(mode="json"),
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.patch(
    "/{patient_id}/notifications/{notification_id}/read",
    response_model=SuccessResponse,
)
async def mark_notification_read(
    patient_id: str,
    notification_id: str,
    service: PatientNotificationService = Depends(get_patient_notification_service),
    current_actor: Actor = Depends(get_current_actor(**_ACTOR_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    try:
        verified_pid = await resolve_patient_access(
            actor=current_actor,
            patient_id=UUID(patient_id),
            care_provider_access_service=care_provider_access_service,
        )
        updated = await service.mark_read(str(verified_pid), notification_id)
        return SuccessResponse(
            message="Notification marked as read." if updated else "Already read.",
            data=MarkReadResponse(updated=updated).model_dump(),
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.post(
    "/{patient_id}/notifications/read-all",
    response_model=SuccessResponse,
)
async def mark_all_notifications_read(
    patient_id: str,
    service: PatientNotificationService = Depends(get_patient_notification_service),
    current_actor: Actor = Depends(get_current_actor(**_ACTOR_DEPS)),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    try:
        verified_pid = await resolve_patient_access(
            actor=current_actor,
            patient_id=UUID(patient_id),
            care_provider_access_service=care_provider_access_service,
        )
        updated = await service.mark_all_read(str(verified_pid))
        return SuccessResponse(
            message=f"{updated} notifications marked as read.",
            data=MarkReadResponse(updated=updated).model_dump(),
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
