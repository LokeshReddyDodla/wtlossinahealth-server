"""Analytics service that persists observability events and audit trails for weightloss agent flows."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorCollection


class AnalyticsService:
    """
    Thin helper around Mongo collections that persists analytics events and audit traces.
    """

    def __init__(
        self,
        analytics_events_collection: AsyncIOMotorCollection,
        audit_traces_collection: AsyncIOMotorCollection,
    ) -> None:
        self.analytics_events_collection = analytics_events_collection
        self.audit_traces_collection = audit_traces_collection

    async def emit_event(
        self,
        event_type: str,
        user_id: Optional[str],
        payload: Optional[Dict[str, Any]] = None,
        source: str = "patient_app",
        severity: str = "info",
    ) -> Dict[str, Any]:
        doc = {
            "event_id": str(uuid4()),
            "event_type": event_type,
            "user_id": user_id,
            "payload": payload or {},
            "source": source,
            "severity": severity,
            "emitted_at": datetime.now(timezone.utc),
        }
        await self.analytics_events_collection.insert_one(doc)
        doc.pop("_id", None)
        return doc

    async def record_audit_trace(
        self,
        trace_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        doc = {
            **trace_payload,
            "trace_entry_id": str(uuid4()),
            "recorded_at": datetime.now(timezone.utc),
        }
        await self.audit_traces_collection.insert_one(doc)
        doc.pop("_id", None)
        return doc
