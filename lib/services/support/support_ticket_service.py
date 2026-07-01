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
from lib.services.chat.message_enricher import (
    enrich_messages_with_sender_profiles,
)
from lib.services.chat.profile_resolver_service import ProfileResolverService
from lib.utils.preview import sanitize_preview


def _preview(text: str, limit: int = 200) -> str:
    """Thin wrapper over ``sanitize_preview`` used for the ticket's
    persisted ``last_message_preview`` field. Aligned at 200 chars with
    the socket-event preview so the stored value and the wire value
    match exactly — no ellipsis, plain text only."""
    return sanitize_preview(text, max_len=limit)


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
        # Drop facility_id on product-scope tickets so we don't store
        # semantically inconsistent data ("product ticket at facility X").
        if scope == "product":
            health_facility_id = None
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
    ) -> tuple[list[dict], int]:
        query: dict = {"requester_id": requester_id}
        if status_filter:
            query["status"] = status_filter
        col = self.mongo_store.db["support_tickets"]
        total = await col.count_documents(query)
        cursor = (
            col.find(query)
            .sort("last_message_at", -1)
            .skip(offset)
            .limit(limit)
        )
        tickets = await cursor.to_list(length=limit)
        return tickets, total

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
        agent_id: str,
        agent_scopes: list[SupportScopeLiteral],
        agent_facility_ids: list[str],
        scope_filter: Optional[SupportScopeLiteral],
        status_filter: Optional[SupportTicketStatusLiteral],
        requester_type_filter: Optional[RequesterTypeLiteral],
        search: Optional[str] = None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict], int]:
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
            return [], 0

        query: dict = (
            scope_clauses[0]
            if len(scope_clauses) == 1
            else {"$or": scope_clauses}
        )
        if status_filter:
            query["status"] = status_filter
        if requester_type_filter:
            query["requester_type"] = requester_type_filter

        col = self.mongo_store.db["support_tickets"]

        if search:
            import re
            pattern = re.escape(search)
            regex = {"$regex": pattern, "$options": "i"}
            # fetch all scope-matched tickets, enrich, then filter by name/subject/preview
            all_cursor = col.find(query).sort("last_message_at", -1)
            all_tickets = await all_cursor.to_list(length=None)
            all_tickets = await self._enrich_with_requester_profiles(all_tickets)

            filtered = []
            for t in all_tickets:
                haystack = " ".join(filter(None, [
                    t.get("subject"),
                    t.get("last_message_preview"),
                    t.get("requester_profile", {}).get("first_name"),
                    t.get("requester_profile", {}).get("last_name"),
                ]))
                if re.search(pattern, haystack, re.IGNORECASE):
                    filtered.append(t)

            total = len(filtered)
            page = filtered[offset : offset + limit]
            page = await self._attach_unread_flags(page, agent_id)
            return page, total

        total = await col.count_documents(query)
        cursor = (
            col.find(query)
            .sort("last_message_at", -1)
            .skip(offset)
            .limit(limit)
        )
        tickets = await cursor.to_list(length=limit)

        tickets = await self._enrich_with_requester_profiles(tickets)
        tickets = await self._attach_unread_flags(tickets, agent_id)

        return tickets, total

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
        agent_id: str,
        agent_scopes: list[SupportScopeLiteral],
        agent_facility_ids: list[str],
    ) -> Optional[dict]:
        """Return ticket + the full message thread. Agents need this to read
        a ticket BEFORE they reply — at which point they're not yet a chat
        participant, so the participant-gated /chats/messages 403s them.

        Also marks the ticket as read for this agent."""
        ticket = await self.get_ticket_for_agent(
            ticket_id, agent_scopes, agent_facility_ids
        )
        if not ticket:
            return None

        await self._mark_read(ticket_id, agent_id)

        messages = (
            await self.mongo_store.db["chat_messages"]
            .find({"chat_id": ticket["chat_id"]})
            .sort("timestamp", 1)
            .to_list(length=None)
        )
        messages = await enrich_messages_with_sender_profiles(messages)
        enriched = await self._enrich_with_requester_profiles([ticket])
        return {**enriched[0], "messages": messages}

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
        # Only join the chat on the agent's FIRST reply — add_participant_in_chat
        # is idempotent at the DB level but the read+write costs add up on a
        # busy thread. Skip when the agent is already a participant.
        chat = await self.mongo_store.db["chats"].find_one(
            {"_id": ticket["chat_id"]},
            {"participants.id": 1},
        )
        already_participant = any(
            p.get("id") == agent_id
            for p in (chat or {}).get("participants", [])
        )
        if not already_participant:
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
            await self._emit_status_change(
                ticket=ticket,
                new_status="pending",
            )

        return await self.mongo_store.db["support_tickets"].find_one(
            {"_id": ticket_id}
        )

    async def on_requester_message_in_support_chat(
        self,
        chat_id: str,
        sender_id: str,
        content: str,
    ) -> None:
        """Hook called from ChatMessagingService.add_message whenever a
        message lands on a support chat.

        Responsibilities:
        - Keep the ticket's ``last_message_at`` / ``last_message_preview``
          in sync with the chat so queue sort surfaces the freshest
          activity — without this, a requester reply leaves the ticket
          stale at the bottom of the agent queue.
        - When the sender is the requester AND the ticket is in a terminal
          state (resolved/closed), reopen it to ``open`` (needs agent
          attention) and emit the status change.

        Agent replies are handled by ``agent_reply`` directly and skipped
        here so we never double-update.
        """
        ticket = await self.mongo_store.db["support_tickets"].find_one(
            {"chat_id": chat_id}
        )
        if not ticket:
            return
        if str(sender_id) != str(ticket["requester_id"]):
            # Agent reply — agent_reply owns the update path.
            return

        now = datetime.utcnow()
        should_reopen = ticket["status"] in ("resolved", "closed")
        update: dict = {
            "updated_at": now,
            "last_message_at": now,
            "last_message_preview": _preview(content),
        }
        if should_reopen:
            update["status"] = "open"

        await self.mongo_store.db["support_tickets"].update_one(
            {"_id": ticket["_id"]}, {"$set": update}
        )

        if should_reopen:
            await self._emit_status_change(ticket=ticket, new_status="open")

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

    async def _enrich_with_requester_profiles(
        self, tickets: list[dict]
    ) -> list[dict]:
        if not tickets:
            return tickets
        requester_ids = {t["requester_id"] for t in tickets}
        profiles = await ProfileResolverService().resolve(requester_ids)
        for t in tickets:
            profile = profiles.get(t["requester_id"])
            if profile is not None:
                t["requester_profile"] = jsonable_encoder(profile)
        return tickets

    async def _mark_read(self, ticket_id: str, agent_id: str) -> None:
        await self.mongo_store.db["support_ticket_reads"].update_one(
            {"_id": f"{agent_id}:{ticket_id}"},
            {"$set": {
                "agent_id": agent_id,
                "ticket_id": ticket_id,
                "read_at": datetime.utcnow(),
            }},
            upsert=True,
        )

    async def _attach_unread_flags(
        self, tickets: list[dict], agent_id: str
    ) -> list[dict]:
        if not tickets:
            return tickets
        ticket_ids = [t["_id"] for t in tickets]
        reads = (
            await self.mongo_store.db["support_ticket_reads"]
            .find({
                "agent_id": agent_id,
                "ticket_id": {"$in": ticket_ids},
            })
            .to_list(length=len(ticket_ids))
        )
        read_map = {r["ticket_id"]: r["read_at"] for r in reads}
        for t in tickets:
            read_at = read_map.get(t["_id"])
            t["has_unread"] = read_at is None or t["last_message_at"] > read_at
        return tickets

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

        await self._emit_status_change(ticket=ticket, new_status=new_status)

        refreshed = await self.mongo_store.db["support_tickets"].find_one(
            {"_id": ticket["_id"]}
        )
        return jsonable_encoder(refreshed)

    async def _emit_status_change(
        self,
        ticket: dict,
        new_status: SupportTicketStatusLiteral,
    ) -> None:
        """Broadcast a status change.

        Two audiences need it and they barely overlap:
        - chat participants (requester + already-engaged agents) get it via
          the standard participant fan-out so their inbox refreshes
        - queue-watching agents who haven't joined the chat yet get it via
          SupportNotificationService.emit_to_queue_agents, otherwise the
          only signal is polling

        Payload uses the forward-compatible (change, ticket_status) shape
        so the Flutter client can patch a single row instead of refetching
        the list. Old clients ignore the extra fields.
        """
        from lib.services.support.support_notification_service import (
            SupportNotificationService,
        )

        payload = {
            "chat_id": ticket["chat_id"],
            "change": "status",
            "ticket_status": new_status,
        }
        await self.chat_notification_service.notify_participants(
            message_key=EmitMessageKeyEnum.CHAT_LIST_UPDATED.value,
            data=payload,
            chat_id=ticket["chat_id"],
        )
        await SupportNotificationService().emit_to_queue_agents(
            chat_id=ticket["chat_id"],
            ticket=ticket,
            event_key=EmitMessageKeyEnum.CHAT_LIST_UPDATED.value,
            data=payload,
        )
