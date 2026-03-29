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
from lib.core.container import container
from lib.ai_foundation.agents.proactive_monitor.contracts import SEVERITY_RANK
from lib.dependencies.actor import Actor, get_current_actor
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
):
    """Manually trigger a proactive health scan for a patient. Admin only.

    Scans the patient's recent data and returns structured health insights.
    Optionally sends FCM notification to a different user (for testing).
    """
    from lib.ai_foundation.agents.proactive_monitor import ProactiveMonitorAgent

    monitor: ProactiveMonitorAgent = container.resolve(ProactiveMonitorAgent)

    # Resolve patient name + timezone
    patient_name = None
    tz_name = None
    try:
        from lib.ai_foundation.agents.health_query.patient_resolver import PatientNameResolver
        resolver: PatientNameResolver = container.resolve(PatientNameResolver)
        names = await resolver.resolve_names([payload.patient_id])
        timezones = await resolver.resolve_timezones([payload.patient_id])
        patient_name = names.get(payload.patient_id)
        tz_name = timezones.get(payload.patient_id)
    except Exception:
        pass

    # Run the scan
    result = await monitor.scan_patient(payload.patient_id, patient_name, tz_name=tz_name)
    if result.error:
        raise HTTPException(status_code=503, detail=f"Proactive scan failed: {result.error}")

    # Send notifications
    notification_target = payload.notification_id or payload.patient_id
    if result.insights:
        try:
            from lib.services.fcm_service import FCMService
            fcm = FCMService()
            # Send only the most severe insight — avoid notification spam
            notifiable = list(result.insights)
            if notifiable:
                top_insight = max(notifiable, key=lambda i: SEVERITY_RANK.get(i.severity.value, 0))
                is_urgent = top_insight.severity.value in ("warning", "alert")
                await fcm.send_fcm_notification_to_user_devices(
                    user_id=notification_target,
                    title=top_insight.title,
                    body=top_insight.body,
                    channel_key="alerts" if is_urgent else "reminders",
                    group_key="alert_group" if is_urgent else "reminder_group",
                    data={
                        "type": "proactive_insight",
                        "insight_id": top_insight.insight_id,
                        "category": top_insight.category.value,
                        "severity": top_insight.severity.value,
                        "patient_id": payload.patient_id,
                        "suggested_query": top_insight.suggested_query or "",
                        "total_insights": str(len(result.insights)),
                    },
                )
                # Record only the insight we actually sent
                await monitor.record_insight(payload.patient_id, top_insight)
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
