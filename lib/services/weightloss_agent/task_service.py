"""Task service for weightloss agent daily tasks."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from motor.motor_asyncio import AsyncIOMotorCollection


class TaskService:
    def __init__(self, tasks_collection: AsyncIOMotorCollection) -> None:
        self.tasks_collection = tasks_collection

    async def get_task(
        self, user_id: UUID, task_type: str, date_str: str
    ) -> Optional[Dict[str, Any]]:
        return await self.tasks_collection.find_one(
            {
                "user_id": str(user_id),
                "task_type": task_type,
                "date": date_str,
            }
        )

    async def get_task_by_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        return await self.tasks_collection.find_one({"task_id": task_id})

    async def get_pending_task(
        self, user_id: UUID, task_type: str, date_str: str
    ) -> Optional[Dict[str, Any]]:
        return await self.tasks_collection.find_one(
            {
                "user_id": str(user_id),
                "task_type": task_type,
                "date": date_str,
                "status": "pending",
            }
        )

    async def get_pending_tasks_for_date(
        self, user_id: UUID, date_str: str
    ) -> List[Dict[str, Any]]:
        cursor = self.tasks_collection.find(
            {
                "user_id": str(user_id),
                "date": date_str,
                "status": "pending",
            }
        )
        return await cursor.to_list(length=None)

    async def create_task(
        self,
        user_id: UUID,
        task_type: str,
        date_str: str,
        *,
        target_value: Optional[float] = None,
        status: str = "pending",
        source: str = "plan",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        doc = {
            "task_id": str(uuid4()),
            "user_id": str(user_id),
            "task_type": task_type,
            "date": date_str,
            "target_value": target_value,
            "status": status,
            "source": source,
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
        }
        await self.tasks_collection.insert_one(doc)
        return doc

    async def get_or_create_task(
        self,
        user_id: UUID,
        task_type: str,
        date_str: str,
        *,
        target_value: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        existing = await self.get_task(user_id, task_type, date_str)
        if existing:
            return existing
        return await self.create_task(
            user_id,
            task_type,
            date_str,
            target_value=target_value,
            metadata=metadata,
        )

    async def mark_task_done(
        self, task_id: str, *, source: str = "manual"
    ) -> None:
        await self.tasks_collection.update_one(
            {"task_id": task_id},
            {
                "$set": {
                    "status": "done",
                    "source": source,
                    "completed_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

    async def mark_task_skipped(
        self, task_id: str, *, source: str = "manual"
    ) -> None:
        await self.tasks_collection.update_one(
            {"task_id": task_id},
            {
                "$set": {
                    "status": "skipped",
                    "source": source,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

    async def update_task_metadata(
        self, task_id: str, metadata_updates: Dict[str, Any]
    ) -> None:
        await self.tasks_collection.update_one(
            {"task_id": task_id},
            {
                "$set": {
                    **{f"metadata.{k}": v for k, v in metadata_updates.items()},
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
