"""Business logic for support tickets.

Each ticket owns one chat (``chat.kind == "support"``).  All messages are
written through the regular chat path so Socket.IO, FCM, attachments, and
read receipts work without duplication.  This service handles only the
ticketing concerns: open, list, agent reply (which adds the agent as a chat
participant), status transitions.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from loguru import logger

from lib.core.constants import EmitMessageKeyEnum, ProfileTypeEnum
from lib.core.mongo_store import get_mongo_store
from lib.core.types import SupportScopeLiteral, SupportTicketStatusLiteral
from lib.schemas.chat_message import (
    ChatMessageCreate,
    MediaSchema,
    MetadataSchema,
)
from lib.schemas.support_ticket import (
    RequesterTypeLiteral,
    SupportTicketSchema,
)
from lib.services.chat.chat_management_service import ChatManagementService
from lib.services.chat.chat_messaging_service import ChatMessagingService
from lib.services.chat.chat_notification_service import ChatNotificationService
from lib.services.chat.chat_participant_service import ChatParticipantService


def _preview(text: str, limit: int = 120) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _normalize_uuid(value: Optional[str]) -> Optional[str]:
    """Canonicalize a UUID-ish string to lowercase 8-4-4-4-12 form so the
    string we store on the ticket matches ``str(UUID)`` from PG. Raises
    ``ValueError`` for malformed input."""
    if value is None:
        return None
    return str(UUID(str(value)))


class SupportTicketService:
    def __init__(self):
        self.mongo_store = get_mongo_store()
        self.chat_management_service = ChatManagementService()
        self.chat_messaging_service = ChatMessagingService()
        self.chat_participant_service = ChatParticipantService()
        self.chat_notification_service = ChatNotificationService()

    # -- requester-facing -------------------------------------------------

    async def open_ticket(
        self,
        *,
        requester_id: str,
        requester_type: RequesterTypeLiteral,
        scope: SupportScopeLiteral,
        initial_message: str,
        media: Optional[MediaSchema],
        subject: Optional[str],
        health_facility_id: Optional[str],
    ) -> dict:
        if scope == "facility" and not health_facility_id:
            raise ValueError(
                "health_facility_id is required when scope == 'facility'"
            )
        try:
            health_facility_id = _normalize_uuid(health_facility_id)
        except ValueError as e:
            raise ValueError(f"Invalid health_facility_id: {e}")

        chat_id = await self.chat_management_service.create_new_chat(
            user_id=requester_id,
            other_user_id=requester_id,
            type=requester_type,
            is_group=False,
            kind="support",
        )

        now = datetime.utcnow()
        ticket = SupportTicketSchema(
            chat_id=chat_id,
            scope=scope,
            requester_id=requester_id,
            requester_type=requester_type,
            health_facility_id=health_facility_id,
            subject=subject,
            status="open",
            created_at=now,
            updated_at=now,
            last_message_at=now,
            last_message_preview=_preview(initial_message),
        )
        ticket_dict = ticket.model_dump(by_alias=True)
        await self.mongo_store.insert_document("support_tickets", ticket_dict)
        logger.info(f"Support ticket {ticket.id} opened by {requester_id}")

        message_data = ChatMessageCreate(
            chat_id=chat_id,
            sender_id=requester_id,
            content=initial_message,
            media=media,
            timestamp=now.replace(tzinfo=None),
            metadata=MetadataSchema(
                type=media.type if media else "text",
                status="sent",
            ),
            severity="low",
            is_flagged=False,
        )
        await self.chat_messaging_service.add_message(message_data)

        return ticket_dict

    async def list_tickets_for_requester(
        self,
        requester_id: str,
        status_filter: Optional[SupportTicketStatusLiteral],
        limit: int,
        offset: int,
    ) -> list[dict]:
        query: dict = {"requester_id": requester_id}
        if status_filter:
            query["status"] = status_filter
        cursor = (
            self.mongo_store.db["support_tickets"]
            .find(query)
            .sort("last_message_at", -1)
            .skip(offset)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)

    async def get_ticket_for_requester(
        self, ticket_id: str, requester_id: str
    ) -> Optional[dict]:
        return await self.mongo_store.db["support_tickets"].find_one(
            {"_id": ticket_id, "requester_id": requester_id}
        )

    async def close_ticket_by_requester(
        self, ticket_id: str, requester_id: str
    ) -> Optional[dict]:
        ticket = await self.get_ticket_for_requester(ticket_id, requester_id)
        if not ticket:
            return None
        return await self._set_status(ticket, "closed")

    # -- agent-facing -----------------------------------------------------

    async def list_queue(
        self,
        *,
        agent_scopes: list[SupportScopeLiteral],
        agent_facility_ids: list[str],
        scope_filter: Optional[SupportScopeLiteral],
        status_filter: Optional[SupportTicketStatusLiteral],
        requester_type_filter: Optional[RequesterTypeLiteral],
        limit: int,
        offset: int,
    ) -> list[dict]:
        scope_clauses: list[dict] = []
        if "product" in agent_scopes and (
            scope_filter is None or scope_filter == "product"
        ):
            scope_clauses.append({"scope": "product"})
        if "facility" in agent_scopes and (
            scope_filter is None or scope_filter == "facility"
        ):
            if agent_facility_ids:
                scope_clauses.append(
                    {
                        "scope": "facility",
                        "health_facility_id": {"$in": agent_facility_ids},
                    }
                )

        if not scope_clauses:
            return []

        query: dict = (
            scope_clauses[0]
            if len(scope_clauses) == 1
            else {"$or": scope_clauses}
        )
        if status_filter:
            query["status"] = status_filter
        if requester_type_filter:
            query["requester_type"] = requester_type_filter

        cursor = (
            self.mongo_store.db["support_tickets"]
            .find(query)
            .sort("last_message_at", -1)
            .skip(offset)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)

    async def get_ticket_for_agent(
        self,
        ticket_id: str,
        agent_scopes: list[SupportScopeLiteral],
        agent_facility_ids: list[str],
    ) -> Optional[dict]:
        ticket = await self.mongo_store.db["support_tickets"].find_one(
            {"_id": ticket_id}
        )
        if not ticket:
            return None
        if not self._agent_can_access_ticket(
            ticket, agent_scopes, agent_facility_ids
        ):
            return None
        return ticket

    async def get_ticket_with_messages_for_agent(
        self,
        ticket_id: str,
        agent_scopes: list[SupportScopeLiteral],
        agent_facility_ids: list[str],
    ) -> Optional[dict]:
        """Return ticket + the full message thread. Agents need this to read
        a ticket BEFORE they reply — at which point they're not yet a chat
        participant, so the participant-gated /chats/messages 403s them."""
        ticket = await self.get_ticket_for_agent(
            ticket_id, agent_scopes, agent_facility_ids
        )
        if not ticket:
            return None
        messages = (
            await self.mongo_store.db["chat_messages"]
            .find({"chat_id": ticket["chat_id"]})
            .sort("timestamp", 1)
            .to_list(length=None)
        )
        return {**ticket, "messages": messages}

    async def agent_reply(
        self,
        *,
        ticket_id: str,
        agent_id: str,
        agent_role: ProfileTypeEnum,
        agent_scopes: list[SupportScopeLiteral],
        agent_facility_ids: list[str],
        content: str,
        media: Optional[MediaSchema],
    ) -> Optional[dict]:
        ticket = await self.get_ticket_for_agent(
            ticket_id, agent_scopes, agent_facility_ids
        )
        if not ticket:
            return None

        agent_participant_type = (
            "admin"
            if agent_role == ProfileTypeEnum.ADMIN
            else "care_provider"
        )
        await self.chat_participant_service.add_participant_in_chat(
            chat_id=ticket["chat_id"],
            user_id=agent_id,
            type=agent_participant_type,
        )

        now = datetime.utcnow()
        message_data = ChatMessageCreate(
            chat_id=ticket["chat_id"],
            sender_id=agent_id,
            content=content,
            media=media,
            timestamp=now.replace(tzinfo=None),
            metadata=MetadataSchema(
                type=media.type if media else "text",
                status="sent",
            ),
            severity="low",
            is_flagged=False,
        )
        await self.chat_messaging_service.add_message(message_data)

        # Open tickets stay open; an agent reply on a closed/resolved
        # ticket reopens it as 'pending' so the queue surfaces it again.
        reopened = ticket["status"] in ("resolved", "closed")
        await self.mongo_store.db["support_tickets"].update_one(
            {"_id": ticket_id},
            {
                "$set": {
                    "updated_at": now,
                    "last_message_at": now,
                    "last_message_preview": _preview(content),
                    **({"status": "pending"} if reopened else {}),
                }
            },
        )

        if reopened:
            # Implicit status flip needs its own chat_list_updated so the
            # requester's inbox refreshes status without a refetch.
            # new_message_received already fires via add_message above and
            # acts as belt-and-braces. Payload uses the forward-compatible
            # (change, ticket_status) shape — additional fields, no
            # existing consumer change.
            await self.chat_notification_service.notify_participants(
                message_key=EmitMessageKeyEnum.CHAT_LIST_UPDATED.value,
                data={
                    "chat_id": ticket["chat_id"],
                    "change": "status",
                    "ticket_status": "pending",
                },
                chat_id=ticket["chat_id"],
            )

        return await self.mongo_store.db["support_tickets"].find_one(
            {"_id": ticket_id}
        )

    async def change_status(
        self,
        *,
        ticket_id: str,
        agent_scopes: list[SupportScopeLiteral],
        agent_facility_ids: list[str],
        new_status: SupportTicketStatusLiteral,
    ) -> Optional[dict]:
        ticket = await self.get_ticket_for_agent(
            ticket_id, agent_scopes, agent_facility_ids
        )
        if not ticket:
            return None
        return await self._set_status(ticket, new_status)

    # -- internals --------------------------------------------------------

    @staticmethod
    def _agent_can_access_ticket(
        ticket: dict,
        agent_scopes: list[SupportScopeLiteral],
        agent_facility_ids: list[str],
    ) -> bool:
        if ticket["scope"] == "product":
            return "product" in agent_scopes
        if ticket["scope"] == "facility":
            return (
                "facility" in agent_scopes
                and ticket.get("health_facility_id") in agent_facility_ids
            )
        return False

    async def _set_status(
        self, ticket: dict, new_status: SupportTicketStatusLiteral
    ) -> dict:
        now = datetime.utcnow()
        update: dict = {"status": new_status, "updated_at": now}
        if new_status == "resolved" and not ticket.get("resolved_at"):
            update["resolved_at"] = now
        if new_status == "closed" and not ticket.get("closed_at"):
            update["closed_at"] = now

        await self.mongo_store.db["support_tickets"].update_one(
            {"_id": ticket["_id"]}, {"$set": update}
        )

        await self.chat_notification_service.notify_participants(
            message_key=EmitMessageKeyEnum.CHAT_LIST_UPDATED.value,
            data={"chat_id": ticket["chat_id"]},
            chat_id=ticket["chat_id"],
        )

        refreshed = await self.mongo_store.db["support_tickets"].find_one(
            {"_id": ticket["_id"]}
        )
        return jsonable_encoder(refreshed)
