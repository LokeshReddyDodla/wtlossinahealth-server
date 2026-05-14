from datetime import datetime
import logging
from typing import Optional

from pymongo.errors import PyMongoError

from lib.core.constants import EmitMessageKeyEnum, ProfileTypeEnum
from lib.core.mongo_store import get_mongo_store
from lib.core.types import ChatKindLiteral, ProfileTypeLiteral
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.pipelines.chat_pipelines import (
    get_chat_messages_pipeline,
    get_single_chat_pipeline,
    get_user_chat_pipeline,
    get_user_messages_pipeline,
)
from lib.schemas.chat import ChatSchema, ParticipantSchema
from lib.services.chat.base import BaseChatService
from lib.services.chat.chat_exceptions import ChatCreationError
from lib.services.chat.chat_notification_service import ChatNotificationService
from lib.services.chat.chat_participant_service import ChatParticipantService
from lib.utils.http_exceptions import raise_http_exception
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class ChatManagementService(BaseChatService):
    def __init__(self):
        self.mongo_store = get_mongo_store()
        self.participant_service = ChatParticipantService()
        self.chat_notification_service = ChatNotificationService()

    async def create_new_chat(
        self,
        user_id: str,
        other_user_id: str,
        type: ProfileTypeLiteral,
        is_group: bool,
        group_name: Optional[str] = None,
        is_read_only: Optional[bool] = False,
        is_muted: Optional[bool] = False,
        is_archived: Optional[bool] = False,
        is_pinned: Optional[bool] = False,
        kind: ChatKindLiteral = "direct",
    ):
        if not is_group and kind != "support":
            # Check for an existing chat. Support tickets always create a
            # fresh chat — each ticket is its own thread.
            existing_chat_id = await self._find_existing_1on1_chat(
                user_id_1=user_id, user_id_2=other_user_id
            )
            if existing_chat_id:
                logger.info(f"Chat already exists with ID: {existing_chat_id}")
                await self.reactivate_direct_chat(user_id, other_user_id)
                return existing_chat_id
            else:
                logger.info("No existing 1-on-1 chat found.")

        participant = ParticipantSchema(
            id=user_id,
            type=type,
            is_read_only=is_read_only,
            is_muted=is_muted,
            is_archived=is_archived,
            is_pinned=is_pinned,
        )

        unread_counts = {participant.id: 0}
        chat = ChatSchema(
            is_group=is_group,
            kind=kind,
            participants=[participant],
            last_message=None,
            unread_counts=unread_counts,
            alias_name=group_name if is_group else None,
            alias_profile_picture=None,
            description=None,
        )

        chat_dict = chat.model_dump(by_alias=True)
        try:
            await self.mongo_store.insert_document("chats", chat_dict)
            logger.info(f"New chat created with ID: {chat.id}")
            # Tell the creator their inbox has a new row. The 1-on-1
            # reactivate branch above doesn't reach here — not a new
            # chat, just a flag flip. Redundant on the open_ticket path
            # (caller already has chat_id from the POST response) but
            # idempotent at the client and keeps consumers uniform.
            from lib.services.socketio_service import sio

            await sio.emit(
                EmitMessageKeyEnum.CHAT_LIST_UPDATED.value,
                {
                    "chat_id": chat.id,
                    "change": "chat_created",
                    "chat_kind": kind,
                },
                room=str(user_id),
            )
            return chat.id
        except PyMongoError as e:
            logger.info(f"Failed to create new chat: {e}")
            raise

    async def create_chat_relationships(
        self,
        patient_id: str,
        care_provider_id: str,
    ):
        try:
            await self.create_direct_and_group_chats(
                patient_id, care_provider_id
            )
            # No standalone emit here — chat_list_updated events are now
            # sourced from the actual mutations:
            # - create_new_chat fires chat_created to the initial
            #   participant (patient) for the direct chat
            # - add_participant_in_chat fires chat_created to the new
            #   joiner (care_provider) and participants_changed to the
            #   existing participant (patient) for each chat the CP joins
            # The previous notify_participants(user_id=patient_id) call
            # fanned an empty-payload event across every chat the patient
            # was in — superseded by the per-chat, payload-rich emits.
        except Exception as e:
            logger.error(f"Chat creation failed: {str(e)}")
            raise ChatCreationError(
                "Failed to create chat relationships"
            ) from e

    async def fetch_user_chats(
        self,
        user_id: str,
    ):
        try:
            pipeline = get_user_chat_pipeline(user_id)
            return (
                await self.mongo_store.db["chats"]
                .aggregate(pipeline)
                .to_list(length=None)
            )

        except PyMongoError as e:
            logger.info(f"MongoDB Error: {e}")
            raise

    async def fetch_user_messages(
        self, user_id: str, last_sync_time: Optional[datetime] = None
    ):
        try:
            pipeline = get_user_messages_pipeline(user_id, last_sync_time)
            return (
                await self.mongo_store.db["chats"]
                .aggregate(pipeline)
                .to_list(length=None)
            )

        except PyMongoError as e:
            logger.info(f"MongoDB Error: {e}")
            raise

    async def fetch_single_chat(
        self, chat_id: str, user_id: str
    ) -> Optional[dict]:
        """Single-chat read in the same shape as one element of
        ``fetch_user_chats``. Returns None when the chat doesn't exist OR
        the user isn't a participant — caller maps to 404."""
        try:
            pipeline = get_single_chat_pipeline(chat_id, user_id)
            rows = (
                await self.mongo_store.db["chats"]
                .aggregate(pipeline)
                .to_list(length=1)
            )
            return rows[0] if rows else None
        except PyMongoError as e:
            logger.info(f"MongoDB Error: {e}")
            raise

    async def fetch_chat_messages(self, chat_id: str, user_id: str):
        try:
            pipeline = get_chat_messages_pipeline(chat_id)
            return (
                await self.mongo_store.db["chat_messages"]
                .aggregate(pipeline)
                .to_list(length=None)
            )
        except PyMongoError as e:
            logger.info(f"MongoDB Error: {e}")
            raise

    async def is_user_in_chat(self, chat_id: str, user_id: str) -> bool:
        """True if the chat exists AND user_id is a participant. Combines
        existence + access check in a single query."""
        chat = await self.mongo_store.db["chats"].find_one(
            {"_id": chat_id, "participants.id": user_id},
            {"_id": 1},
        )
        return chat is not None

    async def find_direct_chat(
        self, user_id_1: str, user_id_2: str
    ) -> Optional[str]:
        try:
            existing_chat = await self.mongo_store.find_document(
                "chats",
                {
                    "is_group": False,
                    "participants.id": {"$all": [user_id_1, user_id_2]},
                    "participants": {"$size": 2},
                },
            )
            return str(existing_chat["_id"]) if existing_chat else None
        except PyMongoError as e:
            logger.info(
                f"Failed to find direct chat between {user_id_1} and {user_id_2}: {e}"
            )
            raise

    async def create_direct_and_group_chats(
        self,
        patient_id: str,
        care_provider_id: str,
    ):
        # Create a direct chat
        chat_id = await self.create_new_chat(
            user_id=patient_id,
            other_user_id=care_provider_id,
            type=ProfileTypeEnum.PATIENT.value,
            is_group=False,
        )
        await self.participant_service.add_participant_in_chat(
            chat_id=chat_id,
            user_id=care_provider_id,
            type=ProfileTypeEnum.CARE_PROVIDER.value,
        )

        # Find the patient's group chat and add the care provider
        group_chat = await self.find_group_chat_for_patient(
            patient_id=patient_id
        )
        if group_chat:
            await self.participant_service.add_participant_in_chat(
                chat_id=group_chat["_id"],
                user_id=care_provider_id,
                type=ProfileTypeEnum.CARE_PROVIDER.value,
            )

    async def find_group_chat_for_patient(self, patient_id: str):
        return await self.mongo_store.find_document(
            "chats",
            {
                "is_group": True,
                "participants": {"$elemMatch": {"id": patient_id}},
            },
        )

    async def disable_direct_chat(
        self, patient_id: str, care_provider_id: str
    ):
        """Disables a direct chat by archiving and making it read-only"""
        await self.mongo_store.update_document_with_array_filters(
            collection_name="chats",
            query={
                "is_group": False,
                "participants.id": {"$all": [patient_id, care_provider_id]},
                "participants": {"$size": 2},
            },
            update={
                "$set": {
                    "participants.$[patient].is_read_only": True,
                    "participants.$[patient].is_archived": True,
                    "participants.$[provider].is_read_only": True,
                    "participants.$[provider].is_archived": True,
                    "updated_at": datetime.utcnow(),
                }
            },
            array_filters=[
                {"patient.id": patient_id},
                {"provider.id": care_provider_id},
            ],
        )

    async def reactivate_direct_chat(
        self, patient_id: str, care_provider_id: str
    ):
        """Re-enables a previously disabled chat"""
        return await self.mongo_store.update_document_with_array_filters(
            collection_name="chats",
            query={
                "is_group": False,
                "participants.id": {"$all": [patient_id, care_provider_id]},
                "participants": {"$size": 2},
            },
            update={
                "$set": {
                    "participants.$[patient].is_read_only": False,
                    "participants.$[patient].is_archived": False,
                    "participants.$[provider].is_read_only": False,
                    "participants.$[provider].is_archived": False,
                    "updated_at": datetime.utcnow(),
                }
            },
            array_filters=[
                {"patient.id": patient_id},
                {"provider.id": care_provider_id},
            ],
        )

    async def delete_direct_chat(self, patient_id: str, care_provider_id: str):
        """Deletes a direct chat between a patient and care provider."""
        await self._delete_chat_with_condition(
            {
                "is_group": False,
                "participants.id": {"$all": [patient_id, care_provider_id]},
                "participants": {"$size": 2},
            }
        )

    async def delete_all_chats(self, user_id: str):
        """Deletes all chats for a given user."""
        await self._delete_chat_with_condition({"participants.id": user_id})

    async def toggle_pin_chat(self, chat_id: str, participant_id: str):
        try:
            from lib.services.socketio_service import sio

            chat_document = await self.mongo_store.db["chats"].find_one(
                {"_id": chat_id}
            )
            if not chat_document:
                raise Exception("Chat not found")

            participant = next(
                (
                    p
                    for p in chat_document["participants"]
                    if p["id"] == participant_id
                ),
                None,
            )
            if not participant:
                raise Exception("Participant not found in chat")

            new_is_pinned_status = not participant.get("is_pinned", False)
            await self.mongo_store.db["chats"].update_one(
                {"_id": chat_id, "participants.id": participant_id},
                {"$set": {"participants.$.is_pinned": new_is_pinned_status}},
            )

            logger.info(
                f"Participant {participant_id} in chat {chat_id} has been {'pinned' if new_is_pinned_status else 'unpinned'}."
            )
            # Rich payload per the unified event contract — the pin
            # toggle is user-private (only the actor's view changes), so
            # this stays scoped to their own room.
            await sio.emit(
                EmitMessageKeyEnum.CHAT_LIST_UPDATED.value,
                {
                    "chat_id": chat_id,
                    "change": "pinned",
                    "is_pinned": new_is_pinned_status,
                    "user_id": participant_id,
                },
                room=participant_id,
            )

        except Exception as e:
            logger.info(
                f"Failed to toggle pin for chat {chat_id} and participant {participant_id}: {str(e)}"
            )
            raise

    async def _delete_chat_with_condition(
        self, condition: dict, delete_messages: bool = False
    ):
        """Deletes chats and associated messages based on a condition."""
        async with await self.mongo_store.client.start_session() as session:
            async with session.start_transaction():
                try:
                    # Find chat documents matching the condition
                    chat_documents = await self.mongo_store.find_many(
                        "chats", condition, {"_id": 1}, session=session
                    )
                    chat_ids = [doc["_id"] for doc in chat_documents]
                    if not chat_ids:
                        logger.info("No chats found for the given condition.")
                        return

                    # Delete the chats
                    await self.mongo_store.delete_many_documents(
                        "chats", {"_id": {"$in": chat_ids}}, session=session
                    )
                    logger.info(f"Deleted chats: {chat_ids}")

                    # Optionally delete associated messages
                    if delete_messages:
                        await self.mongo_store.delete_many_documents(
                            "chat_messages",
                            {"chat_id": {"$in": chat_ids}},
                            session=session,
                        )
                        logger.info(f"Deleted messages for chats: {chat_ids}")

                    await session.commit_transaction()
                except Exception as e:
                    await session.abort_transaction()
                    logger.info(f"Transaction aborted: {e}")
                    raise

    async def _find_existing_1on1_chat(
        self, user_id_1: str, user_id_2: str
    ) -> Optional[str]:
        try:
            existing_chat = await self.mongo_store.find_document(
                "chats",
                {
                    "is_group": False,
                    "participants": {
                        "$all": [
                            {"$elemMatch": {"id": user_id_1}},
                            {"$elemMatch": {"id": user_id_2}},
                        ],
                        "$size": 2,
                    },
                },
            )
            return existing_chat["_id"] if existing_chat else None
        except PyMongoError as e:
            logger.info(f"Failed to check for existing chat: {e}")
            raise
