"""Run the support assistant on a patient's message in a support chat.

Entry point is ``schedule_reply`` (fire-and-forget from the chat send path,
strong task refs held here) which calls ``SupportAssistantService.handle``.

The bot replies only while all of these hold:

- the chat belongs to a support ticket opened by a *patient*;
- the sender is that patient (never the bot itself, never staff);
- no human agent has joined the chat yet (agents become participants on
  their first reply — see ``SupportTicketService.agent_reply``);
- the feature is enabled for the patient's facility;
- the bot has not exhausted its per-ticket reply budget.

Its reply is posted through the normal chat path (socket + push to the
patient), and the ticket document gets an ``assistant`` sub-document the
staff queue can filter and sort on. The bot never changes ticket status.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional
from uuid import uuid4

from loguru import logger

from lib.ai_foundation.agents.state import AgentContext, AgentInput
from lib.ai_foundation.agents.support_assistant import (
    SupportAssistantAgent,
    SupportSnapshot,
    SupportUrgency,
)
from lib.ai_foundation.config import settings
from lib.core.constants import SUPPORT_ASSISTANT_SENDER_ID, AIFeatureEnum
from lib.core.mongo_store import get_mongo_store
from lib.schemas.chat_message import ChatMessageCreate, MetadataSchema
from lib.services.ai_feature_toggle_service import (
    AIFeatureToggleService,
    ai_feature_toggle_service,
)
from lib.services.chat.chat_messaging_service import ChatMessagingService
from lib.services.support.support_assistant_snapshot_service import (
    SupportAssistantSnapshotService,
)

# Strong references so fire-and-forget replies are never garbage-collected
# mid-flight (asyncio only holds weak refs to tasks).
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def schedule_reply(*, chat: Optional[dict], message: dict) -> None:
    """Kick off the assistant for a freshly saved support-chat message
    without blocking the sender's request. Safe to call for any message;
    all eligibility checks happen inside ``handle``."""
    if not chat or chat.get("kind") != "support":
        return
    if str(message.get("sender_id")) == SUPPORT_ASSISTANT_SENDER_ID:
        return

    try:
        # Local import: the container imports the chat services this module
        # is called from, so a top-level import would be circular.
        from lib.core.container import container

        service = container.resolve(SupportAssistantService)
    except Exception as exc:
        logger.warning(f"support assistant: not wired, skipping ({exc})")
        return

    task = asyncio.create_task(
        service.handle(chat=chat, message=message),
        name=f"support-assistant:{message.get('_id')}",
    )
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


class SupportAssistantService:
    def __init__(
        self,
        *,
        agent: SupportAssistantAgent,
        snapshot_service: SupportAssistantSnapshotService,
        chat_messaging_service: ChatMessagingService,
        feature_toggles: AIFeatureToggleService = ai_feature_toggle_service,
        mongo_store=None,
    ):
        self.agent = agent
        self.snapshot_service = snapshot_service
        self.chat_messaging_service = chat_messaging_service
        self.feature_toggles = feature_toggles
        self.mongo_store = mongo_store or get_mongo_store()

    async def handle(self, *, chat: dict, message: dict) -> Optional[dict]:
        """Reply to ``message`` if eligible. Returns ``{"message", "data"}``
        for the posted reply, or ``None`` when the bot stayed silent."""
        chat_id = str(chat["_id"])
        try:
            ticket = await self.mongo_store.db["support_tickets"].find_one(
                {"chat_id": chat_id}
            )
            if not self._is_eligible(chat, ticket, message):
                return None

            patient_id = str(ticket["requester_id"])
            if not await self.feature_toggles.is_enabled_for_patient(
                AIFeatureEnum.SUPPORT_ASSISTANT, patient_id
            ):
                return None

            snapshot = await self._snapshot(patient_id)
            history = await self._history(chat_id, exclude_id=message.get("_id"), requester_id=patient_id)
            trace_id = f"trc_{uuid4().hex[:16]}"

            output = await self.agent.run(
                AgentInput(
                    message=str(message.get("content") or ""),
                    context=AgentContext(
                        patient_id=patient_id,
                        user_id=patient_id,
                        user_role="patient",
                        thread_id=f"support:{ticket['_id']}",
                        trace_id=trace_id,
                        timezone=snapshot.timezone,
                    ),
                    metadata={"history": history, "snapshot": snapshot.model_dump()},
                )
            )

            urgency = str(output.data.get("urgency") or SupportUrgency.NORMAL.value)
            await self.chat_messaging_service.add_message(
                ChatMessageCreate(
                    chat_id=chat_id,
                    sender_id=SUPPORT_ASSISTANT_SENDER_ID,
                    content=output.message,
                    metadata=MetadataSchema(type="text", status="sent"),
                    severity="urgent" if urgency == SupportUrgency.URGENT.value else "low",
                )
            )
            await self._record_on_ticket(ticket["_id"], output.data, trace_id)
            return {"message": output.message, "data": output.data}
        except Exception as exc:
            # Fire-and-forget: log loudly, never propagate into the chat path.
            logger.exception(f"support assistant failed for chat {chat_id}: {exc}")
            return None

    # -- eligibility ------------------------------------------------------------

    @staticmethod
    def _is_eligible(chat: dict, ticket: Optional[dict], message: dict) -> bool:
        if not ticket or ticket.get("requester_type") != "patient":
            return False
        requester_id = str(ticket["requester_id"])
        if str(message.get("sender_id")) != requester_id:
            return False
        humans = [
            p for p in chat.get("participants", [])
            if str(p.get("id")) not in (requester_id, SUPPORT_ASSISTANT_SENDER_ID)
        ]
        if humans:
            return False
        replies = int(((ticket.get("assistant") or {}).get("reply_count")) or 0)
        return replies < settings.SUPPORT_ASSISTANT_MAX_REPLIES_PER_TICKET

    # -- context ------------------------------------------------------------------

    async def _snapshot(self, patient_id: str) -> SupportSnapshot:
        try:
            return await self.snapshot_service.build(patient_id)
        except Exception as exc:
            logger.warning(f"support assistant: snapshot failed for {patient_id}: {exc}")
            return SupportSnapshot(
                lookup_errors=[
                    "care_team", "permissions", "glucose_sources", "meals", "documents", "device",
                ]
            )

    async def _history(
        self, chat_id: str, *, exclude_id, requester_id: str
    ) -> list[dict[str, str]]:
        """Most recent prior messages as [{role, content}], oldest first.
        The patient is ``user``; the bot (and any earlier staff reply) is
        ``assistant``."""
        limit = settings.SUPPORT_ASSISTANT_HISTORY_MESSAGES
        query: dict = {"chat_id": chat_id}
        if exclude_id is not None:
            query["_id"] = {"$ne": exclude_id}
        cursor = (
            self.mongo_store.db["chat_messages"]
            .find(query, {"sender_id": 1, "content": 1, "timestamp": 1})
            .sort("timestamp", -1)
            .limit(limit)
        )
        rows = await cursor.to_list(length=limit)
        history: list[dict[str, str]] = []
        for row in reversed(rows):
            content = (row.get("content") or "").strip()
            if not content:
                continue
            role = "user" if str(row.get("sender_id")) == requester_id else "assistant"
            history.append({"role": role, "content": content})
        return history

    # -- ticket bookkeeping --------------------------------------------------------

    async def _record_on_ticket(self, ticket_id: str, data: dict, trace_id: str) -> None:
        """``$set`` only the ``assistant.*`` fields this service owns, target
        by ``_id``. Status is deliberately untouched."""
        now = datetime.utcnow()
        await self.mongo_store.db["support_tickets"].update_one(
            {"_id": ticket_id},
            {
                "$set": {
                    "assistant.category": data.get("category"),
                    "assistant.urgency": data.get("urgency"),
                    "assistant.needs_human": bool(data.get("needs_human")),
                    "assistant.summary": data.get("summary"),
                    "assistant.handling_mode": data.get("handling_mode"),
                    "assistant.last_replied_at": now,
                    "assistant.last_trace_id": trace_id,
                },
                "$inc": {"assistant.reply_count": 1},
            },
        )
