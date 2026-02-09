"""GLP-1 injection settings storage service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from motor.motor_asyncio import AsyncIOMotorCollection

from lib.schemas.weightloss_agent.agentic_settings import (
    GlpInjectionSettingsRecord,
    GlpInjectionSettingsUpsert,
)


class Glp1InjectionService:
    def __init__(
        self, settings_collection: AsyncIOMotorCollection
    ) -> None:
        self.settings_collection = settings_collection

    async def get_settings(self, user_id: UUID) -> Optional[Dict[str, Any]]:
        return await self.settings_collection.find_one(
            {"user_id": str(user_id)}
        )

    async def upsert_settings(
        self, payload: GlpInjectionSettingsUpsert
    ) -> GlpInjectionSettingsRecord:
        now = datetime.now(timezone.utc)
        doc = {
            "user_id": str(payload.user_id),
            "injection_date": payload.injection_date.isoformat(),
            "injection_frequency_days": payload.injection_frequency_days,
            "timezone": payload.timezone,
            "daily_checkin_time": payload.daily_checkin_time,
            "updated_at": now,
        }
        existing = await self.get_settings(payload.user_id)
        if existing:
            await self.settings_collection.update_one(
                {"user_id": str(payload.user_id)},
                {"$set": doc},
            )
            created_at = existing.get("created_at", now)
        else:
            doc["created_at"] = now
            await self.settings_collection.insert_one(doc)
            created_at = now

        return GlpInjectionSettingsRecord(
            user_id=payload.user_id,
            injection_date=payload.injection_date,
            injection_frequency_days=payload.injection_frequency_days,
            timezone=payload.timezone,
            daily_checkin_time=payload.daily_checkin_time,
            created_at=created_at,
            updated_at=now,
        )

