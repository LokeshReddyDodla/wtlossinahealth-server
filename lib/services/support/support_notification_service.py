"""Fan-out FCM notifications to the support queue for a new ticket message.

For a chat with ``kind == "support"``, the normal chat-participant fan-out
only reaches the requester and any agents who have already replied.  This
service additionally pushes FCM to the wider queue:

- ``scope == "product"``  → all active admins
- ``scope == "facility"`` → all care providers at the ticket's facility
                            whose role is ``support_staff``

Each agent's existing FCM token registry is reused via
``enqueue_fcm_notification_sync`` (same path used for normal chat messages).
"""

from typing import Optional

from loguru import logger
from sqlalchemy.future import select

from lib.core.mongo_store import get_mongo_store
from lib.dependencies.database import get_async_postgres_session
from lib.models.admin import Admin
from lib.models.care_provider import CareProvider
from lib.schemas.fcm_notification_info import FCMNotificationInfo
from lib.workers.tasks.fcm.enqueue import enqueue_fcm_notification_sync


class SupportNotificationService:
    async def notify_queue(
        self,
        chat: dict,
        message: dict,
        sender_id: str,
        notification_info: FCMNotificationInfo,
    ) -> None:
        ticket = await get_mongo_store().db["support_tickets"].find_one(
            {"chat_id": chat["_id"]}
        )
        if not ticket:
            logger.warning(
                f"Support fan-out: no ticket found for chat {chat['_id']}"
            )
            return

        existing_participant_ids = {p["id"] for p in chat.get("participants", [])}
        agents = await self._fetch_queue_agents(
            scope=ticket["scope"],
            health_facility_id=ticket.get("health_facility_id"),
        )

        recipients = [
            {"id": str(a_id), "type": a_type}
            for a_id, a_type in agents
            if str(a_id) not in existing_participant_ids
            and str(a_id) != str(sender_id)
        ]
        if not recipients:
            return

        enqueue_fcm_notification_sync(
            participants=recipients,
            notification_info=notification_info.dict(),
        )
        logger.info(
            f"Support fan-out: queued FCM to {len(recipients)} agent(s) "
            f"for ticket {ticket['_id']}"
        )

    async def _fetch_queue_agents(
        self, scope: str, health_facility_id: Optional[str]
    ) -> list[tuple[str, str]]:
        async with get_async_postgres_session() as session:
            if scope == "product":
                result = await session.execute(
                    select(Admin.id).where(Admin.is_active.is_(True))
                )
                return [(str(row[0]), "admin") for row in result.all()]

            if scope == "facility":
                if not health_facility_id:
                    return []
                result = await session.execute(
                    select(CareProvider.care_provider_id).where(
                        CareProvider.health_facility_id == health_facility_id,
                        CareProvider.role == "support_staff",
                    )
                )
                return [
                    (str(row[0]), "care_provider") for row in result.all()
                ]

        return []
