from datetime import datetime
from typing import Optional

from pymongo.errors import PyMongoError

from lib.core.constants import EmitMessageKey, ProfileType
from lib.core.types import ProfileTypeLiteral
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.pipelines.chat_pipelines import (get_user_chat_pipeline,
                                          get_user_messages_pipeline)
from lib.schemas.chat import ChatSchema, ParticipantSchema
from lib.services.chat.base import BaseChatService
from lib.services.chat.chat_participant_service import ChatParticipantService


class ChatManagementService(BaseChatService):
    def __init__(self):
        self.participant_service = ChatParticipantService()

    async def create_new_chat(
        self,
        user_id: str,
        type: ProfileTypeLiteral,
        is_group: bool,
        group_name: Optional[str] = None,
        is_read_only: Optional[bool] = False,
        is_muted: Optional[bool] = False,
        is_archived: Optional[bool] = False,
        is_pinned: Optional[bool] = False,
    ):

        if not is_group:
            # Check for an existing chat
            existing_chat_id = await self._find_existing_1on1_chat(
                user_id=user_id
            )
            if existing_chat_id:
                print(f"Chat already exists with ID: {existing_chat_id}")
                return existing_chat_id
            else:
                print("No existing 1-on-1 chat found.")

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
            print(f"New chat created with ID: {chat.id}")
            return chat.id
        except PyMongoError as e:
            print(f"Failed to create new chat: {e}")
            raise

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
            print(f"MongoDB Error: {e}")
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
            print(f"MongoDB Error: {e}")
            raise

    async def create_direct_and_group_chats(
        self, patient, care_provider: CareProviderModel  # PatientModel,
    ):
        # Create a direct chat
        chat_id = await self.create_new_chat(
            user_id=str(patient.patient_id),
            type=ProfileType.PATIENT.value,
            is_group=False,
        )
        await self.participant_service.add_participant_in_chat(
            chat_id=chat_id,
            user_id=str(care_provider.care_provider_id),
            type=ProfileType.CARE_PROVIDER.value,
        )

        # Find the patient's group chat and add the care provider
        group_chat = await self.find_group_chat_for_patient(
            patient_id=str(patient.patient_id)
        )
        if group_chat:
            await self.participant_service.add_participant_in_chat(
                chat_id=group_chat["_id"],
                user_id=str(care_provider.care_provider_id),
                type=ProfileType.CARE_PROVIDER.value,
            )

    async def find_group_chat_for_patient(self, patient_id: str):
        return await self.mongo_store.find_document(
            "chats",
            {
                "is_group": True,
                "participants": {"$elemMatch": {"id": patient_id}},
            },
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

            print(
                f"Participant {participant_id} in chat {chat_id} has been {'pinned' if new_is_pinned_status else 'unpinned'}."
            )
            await sio.emit(
                EmitMessageKey.CHAT_LIST_UPDATED.value, room=participant_id
            )

        except Exception as e:
            print(
                f"Failed to toggle pin for chat {chat_id} and participant {participant_id}: {str(e)}"
            )
            raise

    async def _delete_chat_with_condition(self, condition: dict):
        """Deletes chats and associated messages based on a condition."""
        async with await self.mongo_store.client.start_session() as session:
            async with session.start_transaction():
                try:
                    chat_documents = await self.mongo_store.find_many(
                        "chats", condition, {"_id": 1}, session=session
                    )
                    chat_ids = [doc["_id"] for doc in chat_documents]
                    if not chat_ids:
                        print("No chats found for the given condition.")
                        return

                    await self.mongo_store.delete_many_documents(
                        "chats", {"_id": {"$in": chat_ids}}, session=session
                    )
                    await self.mongo_store.delete_many_documents(
                        "chat_messages",
                        {"chat_id": {"$in": chat_ids}},
                        session=session,
                    )

                    print(f"Deleted chats: {chat_ids}")
                    await session.commit_transaction()
                except Exception as e:
                    await session.abort_transaction()
                    print(f"Transaction aborted: {e}")
                    raise

    async def _find_existing_1on1_chat(
        self,
        user_id: str,
    ) -> Optional[str]:
        try:
            existing_chat = await self.mongo_store.find_document(
                "chats",
                {
                    "is_group": False,
                    "participants.id": user_id,
                    "participants": {"$size": 2},
                },
            )
            return existing_chat["_id"] if existing_chat else None
        except PyMongoError as e:
            print(f"Failed to check for existing chat: {e}")
            raise
