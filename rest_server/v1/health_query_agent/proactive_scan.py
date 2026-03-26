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

from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from lib.core.constants import ProfileTypeEnum
from lib.core.container import container
from lib.dependencies.actor import Actor, get_current_actor
from rest_server.response_models import SuccessResponse

from .router import router


class ProactiveScanRequest(BaseModel):
    patient_id: str = Field(..., description="Patient ID to scan")
    notification_id: Optional[str] = Field(
        None,
        description="User ID to receive the notification. Defaults to patient_id if not provided.",
    )


class ProactiveScanResponse(BaseModel):
    patient_id: str
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

    Scans the patient's recent data using the reasoning engine and returns
    structured health insights. Optionally sends FCM notification to a
    different user (for testing).
    """
    from lib.ai_foundation.agents.proactive_monitor import ProactiveMonitorAgent

    monitor: ProactiveMonitorAgent = container.resolve(ProactiveMonitorAgent)

    # Resolve patient name
    patient_name = None
    try:
        from lib.ai_foundation.agents.health_query.patient_resolver import PatientNameResolver
        resolver: PatientNameResolver = container.resolve(PatientNameResolver)
        names = await resolver.resolve_names([payload.patient_id])
        patient_name = names.get(payload.patient_id)
    except Exception:
        pass

    # Run the scan
    result = await monitor.scan_patient(payload.patient_id, patient_name)

    # Send notifications
    notification_target = payload.notification_id or payload.patient_id
    if result.insights:
        try:
            from lib.services.fcm_service import FCMService
            fcm = FCMService()
            # Send only the most severe insight — avoid notification spam
            severity_rank = {"alert": 4, "warning": 3, "attention": 2, "info": 1}
            notifiable = [i for i in result.insights if i.severity.value in ("attention", "warning", "alert")]
            if notifiable:
                top_insight = max(notifiable, key=lambda i: severity_rank.get(i.severity.value, 0))
                await fcm.send_fcm_notification_to_user_devices(
                    user_id=notification_target,
                    title=top_insight.title,
                    body=top_insight.body,
                    channel_key="health_insights",
                    group_key="health_insights_group",
                    data={
                        "type": "proactive_insight",
                        "category": top_insight.category.value,
                        "severity": top_insight.severity.value,
                        "patient_id": payload.patient_id,
                        "total_insights": str(len(result.insights)),
                    },
                )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("FCM notification failed: %s", exc, exc_info=True)

    return SuccessResponse(
        message=f"Scan complete — {len(result.insights)} insights found",
        data=ProactiveScanResponse(
            patient_id=payload.patient_id,
            notification_sent_to=notification_target,
            insight_count=len(result.insights),
            insights=[i.model_dump(mode="json") for i in result.insights],
        ),
    )
