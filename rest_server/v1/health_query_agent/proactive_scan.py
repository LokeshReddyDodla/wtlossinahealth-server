"""
Proactive Monitor — manual scan endpoint for testing.

Admin-only endpoint to trigger a proactive health scan for a specific patient.
Optionally send the notification to a different user (for testing on yourself).

POST /health-query-agent/proactive-scan
{
    "patient_id": "uuid-of-patient-to-scan",
    "notification_id": "uuid-to-receive-notification"  // optional, defaults to patient_id
}
"""

import logging
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from lib.core.constants import ProfileTypeEnum
from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver
from lib.ai_foundation.agents.proactive_monitor import ProactiveMonitorAgent
from lib.ai_foundation.agents.proactive_monitor.notify import send_top_insight_notification
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import (
    get_patient_name_resolver,
    get_proactive_monitor_agent,
)
from rest_server.response_models import SuccessResponse

logger = logging.getLogger(__name__)

from .router import router


class ProactiveScanRequest(BaseModel):
    patient_id: str = Field(..., description="Patient ID to scan")
    notification_id: Optional[str] = Field(
        None,
        description="User ID to receive the notification. Defaults to patient_id if not provided.",
    )


class ProactiveScanResponse(BaseModel):
    patient_id: str
    scan_date: str
    notification_sent_to: str
    insight_count: int
    insights: list[dict] = Field(default_factory=list)


@router.post("/proactive-scan", response_model=SuccessResponse[ProactiveScanResponse])
async def trigger_proactive_scan(
    payload: ProactiveScanRequest,
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.ADMIN],
            check_permissions=False,
        )
    ),
    monitor: ProactiveMonitorAgent = Depends(get_proactive_monitor_agent),
    resolver: PatientNameResolver = Depends(get_patient_name_resolver),
):
    """Manually trigger a proactive health scan for a patient. Admin only.

    Scans the patient's recent data and returns structured health insights.
    Optionally sends FCM notification to a different user (for testing).
    """
    # Resolve patient name + timezone
    patient_name = None
    tz_name = None
    try:
        names = await resolver.resolve_names([payload.patient_id])
        timezones = await resolver.resolve_timezones([payload.patient_id])
        patient_name = names.get(payload.patient_id)
        tz_name = timezones.get(payload.patient_id)
    except Exception:
        pass

    # Run the scan
    result = await monitor.scan_patient(payload.patient_id, patient_name, tz_name=tz_name)
    if result.error:
        logger.error("Proactive scan failed for %s: %s", payload.patient_id, result.error)
        raise HTTPException(status_code=503, detail="Proactive scan failed. Check server logs.")

    # Send notifications
    notification_target = payload.notification_id or payload.patient_id
    if result.insights:
        try:
            from lib.services.fcm_service import FCMService
            fcm = FCMService()
            await send_top_insight_notification(
                payload.patient_id, result.insights, monitor, fcm,
                notification_target=notification_target,
            )
        except Exception as exc:
            logger.error("FCM notification failed: %s", exc, exc_info=True)

    return SuccessResponse(
        message=f"Scan complete — {len(result.insights)} insights found",
        data=ProactiveScanResponse(
            patient_id=payload.patient_id,
            scan_date=result.scan_date,
            notification_sent_to=notification_target,
            insight_count=len(result.insights),
            insights=[i.model_dump(mode="json") for i in result.insights],
        ),
    )
