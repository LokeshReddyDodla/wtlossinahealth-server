"""Flow engine for weightloss agentic scheduling."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from motor.motor_asyncio import AsyncIOMotorCollection


class FlowEngine:
    def __init__(self, flow_collection: AsyncIOMotorCollection) -> None:
        self.flow_collection = flow_collection

    async def get_flow(
        self, user_id: UUID, flow_type: str
    ) -> Optional[Dict[str, Any]]:
        return await self.flow_collection.find_one(
            {"user_id": str(user_id), "flow_type": flow_type, "status": "active"}
        )

    async def get_or_create_flow(
        self,
        user_id: UUID,
        flow_type: str,
        *,
        state: str = "active",
        state_data: Optional[Dict[str, Any]] = None,
        next_run_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        existing = await self.get_flow(user_id, flow_type)
        if existing:
            return existing
        now = datetime.now(timezone.utc)
        flow_id = uuid4()
        doc = {
            "flow_id": str(flow_id),
            "user_id": str(user_id),
            "flow_type": flow_type,
            "state": state,
            "state_data": state_data or {},
            "next_run_at": next_run_at or now,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        await self.flow_collection.insert_one(doc)
        return doc

    async def create_flow(
        self,
        user_id: UUID,
        flow_type: str,
        *,
        state: str = "scheduled",
        state_data: Optional[Dict[str, Any]] = None,
        next_run_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        flow_id = uuid4()
        doc = {
            "flow_id": str(flow_id),
            "user_id": str(user_id),
            "flow_type": flow_type,
            "state": state,
            "state_data": state_data or {},
            "next_run_at": next_run_at or now,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        await self.flow_collection.insert_one(doc)
        return doc

    async def update_flow(self, flow_id: str, updates: Dict[str, Any]) -> None:
        updates["updated_at"] = datetime.now(timezone.utc)
        await self.flow_collection.update_one(
            {"flow_id": flow_id}, {"$set": updates}
        )

    async def complete_flow(self, flow_id: str) -> None:
        await self.flow_collection.update_one(
            {"flow_id": flow_id},
            {
                "$set": {
                    "status": "completed",
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

    async def get_due_flows(
        self, user_id: UUID, now: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        if not now:
            now = datetime.now(timezone.utc)
        cursor = self.flow_collection.find(
            {
                "user_id": str(user_id),
                "status": "active",
                "next_run_at": {"$lte": now},
            }
        )
        return await cursor.to_list(length=None)

