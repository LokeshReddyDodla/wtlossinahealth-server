from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi.encoders import jsonable_encoder

from lib.core.constants import EmitMessageKeyEnum
from lib.core.mongo_store import get_mongo_store
from lib.schemas.chat_message import ChatMessage, ChatMessageCreate
from lib.schemas.fcm_notification_info import FCMNotificationInfo
from lib.services.chat.base import BaseChatService
from lib.services.chat.chat_notification_service import ChatNotificationService


class ChatMessagingService(BaseChatService):
    def __init__(self):
        self.mongo_store = get_mongo_store()
        self.notification_service = ChatNotificationService()

    async def add_message(self, message_data: ChatMessageCreate):
        """Add a new message to the chat."""
        try:
            message = self._create_message_instance(message_data)
            saved_message = await self._save_message_to_db(message)
            await self._update_chat_on_new_message(
                message, message_data.sender_id
            )

            chat = await self.mongo_store.db["chats"].find_one(
                {"_id": message_data.chat_id}
            )
            chat_kind = (chat or {}).get("kind", "direct")

            notification_info = self._create_notification_info(
                message, chat_kind=chat_kind
            )
            await self.notification_service.notify_participants(
                message_key=EmitMessageKeyEnum.NEW_MESSAGE_RECEIVED.value,
                data=jsonable_encoder(saved_message),
                chat_id=message_data.chat_id,
                notification_info=notification_info,
            )

            if chat_kind == "support":
                # Fan out to agents who aren't (yet) chat participants — the
                # support queue. Import locally to avoid a circular import via
                # SupportTicketService -> ChatMessagingService.
                from lib.services.support.support_notification_service import (
                    SupportNotificationService,
                )

                await SupportNotificationService().notify_queue(
                    chat=chat,
                    message=saved_message,
                    sender_id=message_data.sender_id,
                    notification_info=notification_info,
                )

            print(
                f"Message {message.id} broadcasted to chat {message_data.chat_id}."
            )

        except Exception as e:
            print(f"Failed to add message: {str(e)}")
            raise Exception(f"Failed to add message: {str(e)}")

    async def edit_message(
        self,
        chat_id: str,
        message_id: str,
        sender_id: str,
        new_content: str,
        metadata: Optional[Dict] = None,
    ):
        """Edit the content of a message."""
        try:
            existing_message = await self.get_message_by_id(message_id)

            if existing_message["sender_id"] != sender_id:
                raise Exception("You are not allowed to edit this message")

            update_data = {
                "content": new_content,
                "updated_at": datetime.now(timezone.utc),
                "is_edited": True,
            }
            if metadata:
                update_data["metadata"] = metadata

            result = await self.mongo_store.db["chat_messages"].update_one(
                {"_id": message_id, "chat_id": chat_id}, {"$set": update_data}
            )
            if result.matched_count == 0:
                raise Exception("No matching message found to update.")

            updated_message = {**existing_message, **update_data}

            await self.notification_service.notify_participants(
                message_key=EmitMessageKeyEnum.MESSAGE_UPDATED.value,
                data={
                    **jsonable_encoder(updated_message),
                    "message": jsonable_encoder(
                        updated_message
                    ),  # TODO: remove "message" key after making changes in patient app
                },
                chat_id=chat_id,
            )

            print(f"Message {message_id} updated and broadcasted.")

        except Exception as e:
            print(f"Failed to edit message: {str(e)}")
            raise Exception(f"Failed to edit message: {str(e)}")

    async def mark_message_as_read(
        self, chat_id: str, user_id: str, message_id: str
    ):
        """Mark a specific message as read by the user."""
        try:
            await self._update_message_read_status(
                chat_id, message_id, user_id
            )
            await self._update_chat_unread_count(chat_id, user_id)
            await self.notification_service.notify_participants(
                message_key=EmitMessageKeyEnum.MESSAGE_MARKED_AS_READ.value,
                data={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "user_id": user_id,
                },
                chat_id=chat_id,
            )
        except Exception as e:
            print(f"Failed to mark message as read: {str(e)}")
            raise Exception(f"Failed to mark message as read: {str(e)}")

    async def mark_all_messages_as_read(self, chat_id: str, user_id: str):
        """Mark all messages in a chat as read by the user."""
        try:
            await self._mark_all_messages_as_read_in_chat(chat_id, user_id)
            await self._update_chat_unread_count(chat_id, user_id)
            await self.notification_service.notify_participants(
                message_key=EmitMessageKeyEnum.ALL_MESSAGES_MARKED_AS_READ.value,
                data={"chat_id": chat_id, "user_id": user_id},
                chat_id=chat_id,
            )
        except Exception as e:
            print(f"Failed to mark all messages as read: {str(e)}")
            raise Exception(f"Failed to mark all messages as read: {str(e)}")

    async def toggle_reaction(
        self, chat_id: str, message_id: str, user_id: str, reaction: str
    ):
        """Toggle a reaction for a message."""
        try:
            message = await self.mongo_store.db["chat_messages"].find_one(
                {"_id": message_id, "chat_id": chat_id}
            )
            if not message:
                raise Exception(
                    f"Message {message_id} not found in chat {chat_id}"
                )

            await self._handle_reaction_toggle(
                message, chat_id, message_id, user_id, reaction
            )
        except Exception as e:
            print(f"Failed to toggle reaction: {str(e)}")
            raise Exception(f"Failed to toggle reaction: {str(e)}")

    async def get_message_by_id(self, message_id: str):
        """Fetch a message by its ID."""
        try:
            message = await self.mongo_store.db["chat_messages"].find_one(
                {"_id": message_id}
            )
            if not message:
                raise Exception(f"Message {message_id} not found.")
            return jsonable_encoder(message)
        except Exception as e:
            print(f"Failed to fetch message: {str(e)}")
            raise Exception(f"Failed to fetch message: {str(e)}")

    # Private Helper Methods
    def _create_message_instance(
        self, message_data: ChatMessageCreate
    ) -> ChatMessage:
        """Create a ChatMessage instance from input data."""
        return ChatMessage(
            chat_id=message_data.chat_id,
            sender_id=message_data.sender_id,
            content=message_data.content,
            media=message_data.media,
            reply_to=message_data.reply_to,
            timestamp=message_data.timestamp.replace(tzinfo=None),
            metadata=message_data.metadata,
            severity=message_data.severity or "low",
            is_flagged=message_data.is_flagged or False,
            read_receipts=[],
            reactions=[],
        )

    async def _save_message_to_db(self, message: ChatMessage):
        """Save the message to the database."""
        message_dict = message.model_dump(by_alias=True)
        if message_dict.get("media") and message_dict["media"].get("url"):
            message_dict["media"]["url"] = str(message_dict["media"]["url"])

        await self.mongo_store.insert_document("chat_messages", message_dict)

        print(f"Message {message.id} added to chat {message.chat_id}.")

        return message_dict

    async def _update_chat_on_new_message(
        self, message: ChatMessage, sender_id: str
    ):
        """Update the chat document after a new message is added."""
        await self.mongo_store.db["chats"].update_one(
            {"_id": message.chat_id},
            {
                "$set": {
                    "last_message": message.id,
                    "updated_at": datetime.now(),
                },
                "$inc": {f"unread_counts.{sender_id}": 0},
            },
        )
        chat = await self.mongo_store.db["chats"].find_one(
            {"_id": message.chat_id}
        )
        if chat:
            for participant in chat["participants"]:
                participant_id = participant["id"]
                if participant_id != sender_id:
                    await self.mongo_store.db["chats"].update_one(
                        {"_id": message.chat_id},
                        {"$inc": {f"unread_counts.{participant_id}": 1}},
                    )

    def _create_notification_info(
        self, message: ChatMessage, chat_kind: str = "direct"
    ) -> FCMNotificationInfo:
        """Create notification info for a new message."""
        is_support = chat_kind == "support"
        return FCMNotificationInfo(
            title="Support Update" if is_support else "New Message",
            body=self.notification_service._get_notification_body(
                message.metadata.type, message.content
            ),
            channel_key="support_messages" if is_support else "chat_messages",
            group_key="support_group" if is_support else "chat_group",
            sender_id=message.sender_id,
        )

    async def _update_message_read_status(
        self, chat_id: str, message_id: str, user_id: str
    ):
        """Update a specific message's read receipts."""
        await self.mongo_store.db["chat_messages"].update_one(
            {"_id": message_id, "chat_id": chat_id},
            {
                "$addToSet": {
                    "read_receipts": {
                        "reader_id": user_id,
                        "read_at": datetime.now(),
                    }
                },
                "$set": {"updated_at": datetime.now()},
            },
        )

    async def _update_chat_unread_count(self, chat_id: str, user_id: str):
        """Update the unread count for a user in a chat."""
        unread_message_count = await self.mongo_store.db[
            "chat_messages"
        ].count_documents(
            {
                "chat_id": chat_id,
                "read_receipts": {
                    "$not": {"$elemMatch": {"reader_id": user_id}}
                },
            }
        )
        if unread_message_count == 0:
            await self.mongo_store.db["chats"].update_one(
                {"_id": chat_id},
                {
                    "$set": {
                        f"unread_counts.{user_id}": 0,
                        "updated_at": datetime.now(),
                    }
                },
            )

    async def _mark_all_messages_as_read_in_chat(
        self, chat_id: str, user_id: str
    ):
        """Mark all messages in a chat as read."""
        await self.mongo_store.db["chat_messages"].update_many(
            {"chat_id": chat_id, "read_receipts.reader_id": {"$ne": user_id}},
            {
                "$addToSet": {
                    "read_receipts": {
                        "reader_id": user_id,
                        "read_at": datetime.now(),
                    }
                },
                "$set": {"updated_at": datetime.now()},
            },
        )

    async def _handle_reaction_toggle(
        self,
        message,
        chat_id: str,
        message_id: str,
        user_id: str,
        reaction: str,
    ):
        """Toggle a reaction on a message."""
        current_time = datetime.now()
        user_reaction = next(
            (
                r
                for r in message.get("reactions", [])
                if r["user_id"] == user_id
            ),
            None,
        )

        if user_reaction:
            if user_reaction["reaction"] == reaction:
                await self.mongo_store.db["chat_messages"].update_one(
                    {"_id": message_id, "chat_id": chat_id},
                    {
                        "$pull": {"reactions": {"user_id": user_id}},
                        "$set": {"updated_at": current_time},
                    },
                )
            else:
                await self.mongo_store.db["chat_messages"].update_one(
                    {
                        "_id": message_id,
                        "chat_id": chat_id,
                        "reactions.user_id": user_id,
                    },
                    {
                        "$set": {
                            "reactions.$.reaction": reaction,
                            "updated_at": current_time,
                        }
                    },
                )
        else:
            await self.mongo_store.db["chat_messages"].update_one(
                {"_id": message_id, "chat_id": chat_id},
                {
                    "$addToSet": {
                        "reactions": {"user_id": user_id, "reaction": reaction}
                    },
                    "$set": {"updated_at": current_time},
                },
            )
