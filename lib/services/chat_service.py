from datetime import datetime
from typing import List, Literal, Optional

from faker import Faker
from pymongo.errors import OperationFailure, PyMongoError
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.constants import PROFILE_TYPE_CARE_PROVIDER, PROFILE_TYPE_PATIENT
from lib.core.mongo_store import get_mongo_store
from lib.core.types import ProfileType
from lib.pipelines.chat_pipelines import get_user_chat_pipeline
from lib.schemas.chat import ChatSchema, ParticipantSchema
from lib.schemas.chat_message import ChatMessage, ChatMessageCreate
from lib.services.socketio_service import sio
from lib.utils.serializers import serialize_message

fake = Faker()


class ChatService:
    def __init__(self):
        self.mongo_store = get_mongo_store()

    async def create_new_chat(
        self,
        user_id: str,
        type: ProfileType,
        is_group: bool,
        is_read_only: Optional[bool] = False,
        is_muted: Optional[bool] = False,
        is_archived: Optional[bool] = False,
        is_pinned: Optional[bool] = False,
    ):
        participant = ParticipantSchema(
            id=user_id,
            type=type,
            is_read_only=is_read_only,
            is_muted=is_muted,
            is_archived=is_archived,
            is_pinned=is_pinned,
        )

        # Initialize unread_counts for each participant
        unread_counts = {participant.id: 0}
        random_group_name = f"{fake.color_name()} {fake.word()}"

        chat = ChatSchema(
            is_group=is_group,
            participants=[participant],
            last_message=None,
            unread_counts=unread_counts,
            alias_name=random_group_name if is_group else None,
            alias_profile_picture=None,
            description=None,
        )
        chat_dict = chat.dict(by_alias=True)
        try:
            await self.mongo_store.insert_document("chats", chat_dict)
            print(f"New chat created with ID: {chat.id}")
            return chat.id
        except PyMongoError as e:
            print(f"Failed to create new chat: {e}")
            raise

    async def create_new_chat_with_participants(
        self,
        participants: List[ParticipantSchema],
        is_group: bool,
    ) -> str:

        # Initialize unread_counts for each participant
        unread_counts = {participant.id: 0 for participant in participants}
        random_group_name = f"{fake.color_name()} {fake.word()}"

        chat = ChatSchema(
            is_group=is_group,
            participants=participants,
            last_message=None,
            unread_counts=unread_counts,
            alias_name=random_group_name if is_group else None,
            alias_profile_picture=None,
            description=None,
        )
        chat_dict = chat.dict(by_alias=True)
        try:
            await self.mongo_store.insert_document("chats", chat_dict)
            print(f"New group chat created with ID: {chat.id}")
            return chat.id
        except PyMongoError as e:
            print(f"Failed to create new group chat: {e}")
            raise

    async def add_participant_in_chat(
        self,
        chat_id: str,
        user_id: str,
        type: ProfileType,
        is_read_only: Optional[bool] = False,
        is_muted: Optional[bool] = False,
        is_archived: Optional[bool] = False,
        is_pinned: Optional[bool] = False,
    ):
        participant = ParticipantSchema(
            id=user_id,
            type=type,
            is_read_only=is_read_only,
            is_muted=is_muted,
            is_archived=is_archived,
            is_pinned=is_pinned,
        )
        participant_dict = participant.dict(by_alias=True)

        try:
            # Check if the participant already exists
            existing_participant = await self.mongo_store.db["chats"].find_one(
                {
                    "_id": chat_id,
                    "participants.id": user_id,
                },
                {"participants.$": 1},  # Fetch only the matching participant
            )

            if existing_participant:
                # Update the existing participant
                await self.mongo_store.db["chats"].update_one(
                    {
                        "_id": chat_id,
                        "participants.id": user_id,
                    },
                    {
                        "$set": {
                            "updated_at": datetime.now(),
                            "participants.$": participant_dict,
                        }
                    },
                )
            else:
                # Add the participant if they don't exist
                await self.mongo_store.db["chats"].update_one(
                    {"_id": chat_id},
                    {
                        "$set": {"updated_at": datetime.now()},
                        "$push": {"participants": participant_dict},
                        "$set": {f"unread_counts.{user_id}": 0},
                    },
                )
        except PyMongoError as e:
            print(f"MongoDB Error: {e}")
            raise

    async def get_user_chats(
        self, user_id: str, postgres_session: AsyncSession
    ):
        from lib.services.care_provider_service import CareProviderService
        from lib.services.patient_profile_service import PatientProfileService

        try:
            pipeline = get_user_chat_pipeline(user_id)

            chat_documents = (
                await self.mongo_store.db["chats"]
                .aggregate(pipeline)
                .to_list(length=None)
            )

            # Collect participant IDs by type
            patient_ids = {
                p["id"]
                for chat in chat_documents
                for p in chat["participants"]
                if p["type"] == PROFILE_TYPE_PATIENT
            }
            care_provider_ids = {
                p["id"]
                for chat in chat_documents
                for p in chat["participants"]
                if p["type"] == PROFILE_TYPE_CARE_PROVIDER
            }

            # Fetch profiles for patients from PostgreSQL
            patient_profile_service = PatientProfileService(postgres_session)
            patient_profiles = (
                await patient_profile_service.fetch_patient_profiles(
                    list(patient_ids)
                )
            )

            # Fetch profiles for care providers from PostgreSQL
            care_provider_profile_service = CareProviderService(
                postgres_session
            )
            care_provider_profiles = await care_provider_profile_service.fetch_care_provider_profiles(
                list(care_provider_ids)
            )

            # Merge profiles into chat participants
            for chat in chat_documents:
                sender = chat.get("sender")
                if sender:
                    if sender["type"] == PROFILE_TYPE_PATIENT:
                        sender["profile"] = patient_profiles.get(
                            sender["id"], {}
                        )
                    else:
                        sender["profile"] = care_provider_profiles.get(
                            sender["id"], {}
                        )

                for receiver in chat.get("receiver", []):
                    if receiver["type"] == PROFILE_TYPE_PATIENT:
                        receiver["profile"] = patient_profiles.get(
                            receiver["id"], {}
                        )
                    else:
                        receiver["profile"] = care_provider_profiles.get(
                            receiver["id"], {}
                        )

            return chat_documents

        except PyMongoError as e:
            print(f"MongoDB Error: {e}")
            raise
        except Exception as e:
            raise

    async def toggle_pin_chat(self, chat_id: str, participant_id: str):
        try:
            # Find the chat by chat_id and locate the participant by participant_id
            chat_document = await self.mongo_store.db["chats"].find_one(
                {"_id": chat_id}
            )

            if not chat_document:
                raise Exception("Chat not found")

            # Find the participant in the chat
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

            # Toggle the is_pinned status
            new_is_pinned_status = not participant.get("is_pinned", False)

            # Update the participant in the chat document
            await self.mongo_store.db["chats"].update_one(
                {"_id": chat_id, "participants.id": participant_id},
                {"$set": {"participants.$.is_pinned": new_is_pinned_status}},
            )

            print(
                f"Participant {participant_id} in chat {chat_id} has been {'pinned' if new_is_pinned_status else 'unpinned'}."
            )

            await sio.emit("chatListUpdate", room=participant_id)

        except Exception as e:
            print(
                f"Failed to toggle pin for chat {chat_id} and participant {participant_id}: {str(e)}"
            )
            raise

    async def add_message(self, user_id: str, message_data: ChatMessageCreate):
        message = ChatMessage(
            chat_id=message_data.chat_id,
            sender_id=message_data.sender_id,
            content=message_data.content,
            media=message_data.media,
            reply_to=message_data.reply_to,
            timestamp=message_data.timestamp,
            metadata=message_data.metadata,
            severity=message_data.severity or "low",
            is_flagged=message_data.is_flagged or False,
        )
        message_dict = message.dict(by_alias=True)

        try:
            await self.mongo_store.insert_document(
                "chat_messages", message_dict
            )
            print(
                f"Message {message.id} added to chat {message_data.chat_id}."
            )

            # Update the chat document's last_message_id and updated_at fields
            await self.mongo_store.db["chats"].update_one(
                {"_id": message_data.chat_id},
                {
                    "$set": {
                        "last_message": message.id,
                        "updated_at": datetime.now(),
                    }
                },
            )

            try:
                # Broadcast the message to WebSocket clients in the chat group
                await sio.emit(
                    "newMessage",
                    serialize_message(message_dict),
                    room=user_id,
                )
                print(
                    f"Message {message.id} broadcasted to room {message_data.chat_id}."
                )
            except Exception as e:
                print(f"Failed to broadcast message {message.id}: {e}")
                raise Exception(f"Failed to broadcast message: {str(e)}")

        except Exception as e:
            raise Exception(f"Failed to add message: {str(e)}")

    async def delete_all_chats(self, user_id: str):
        try:
            # Start a client session for transaction
            async with (
                await self.mongo_store.client.start_session()
            ) as session:
                async with session.start_transaction():
                    try:
                        # 1. Find all chats where the user is a participant
                        chat_documents = await self.mongo_store.find_many(
                            "chats",
                            {"participants.id": user_id},
                            {"_id": 1},  # Only retrieve the '_id' field
                            session=session,
                        )
                        chat_ids = [doc["_id"] for doc in chat_documents]

                        if not chat_ids:
                            print(f"No chats found for user {user_id}.")

                        # 2. Delete chats
                        delete_chats_result = (
                            await self.mongo_store.delete_many_documents(
                                "chats",
                                {"_id": {"$in": chat_ids}},
                                session=session,
                            )
                        )
                        print(
                            f"Deleted {delete_chats_result} chats for user {user_id}."
                        )

                        # 3. Delete associated messages
                        delete_messages_result = (
                            await self.mongo_store.delete_many_documents(
                                "chat_messages",
                                {"chat_id": {"$in": chat_ids}},
                                session=session,
                            )
                        )
                        print(
                            f"Deleted {delete_messages_result} messages for chats {chat_ids}."
                        )

                        # Commit transaction if all operations are successful
                        await session.commit_transaction()

                    except Exception as e:
                        # Abort transaction in case of any errors
                        await session.abort_transaction()
                        print(f"Transaction aborted due to error: {e}")
                        raise
        except Exception as e:
            print(f"Unexpected Error: {e}")
            raise

    async def delete_direct_chat(self, patient_id: str, care_provider_id: str):
        try:
            # Start a client session for transaction
            async with (
                await self.mongo_store.client.start_session()
            ) as session:
                async with session.start_transaction():
                    try:
                        # 1. Find the chat where is_group is False and participants include both user_id1 and user_id2
                        chat_documents = await self.mongo_store.find_many(
                            "chats",
                            {
                                "is_group": False,
                                "participants.id": {
                                    "$all": [patient_id, care_provider_id]
                                },
                                "participants": {"$size": 2},
                            },
                            {"_id": 1},  # Only retrieve the 'id' field
                            session=session,
                        )
                        chat_ids = [doc["_id"] for doc in chat_documents]

                        if not chat_ids:
                            print(
                                f"No direct chat found between users {patient_id} and {care_provider_id}."
                            )

                        # Assuming there's only one direct chat between two users
                        chat_id = chat_ids[0]

                        # 2. Delete the chat document
                        delete_chats_result = (
                            await self.mongo_store.delete_many_documents(
                                "chats", {"_id": chat_id}, session=session
                            )
                        )
                        print(
                            f"Deleted chat {chat_id} between users {patient_id} and {care_provider_id}."
                        )

                        # 3. Delete associated messages
                        delete_messages_result = (
                            await self.mongo_store.delete_many_documents(
                                "chat_messages",
                                {"chat_id": chat_id},
                                session=session,
                            )
                        )
                        print(
                            f"Deleted {delete_messages_result} messages for chat {chat_id}."
                        )

                        # Commit transaction if all operations are successful
                        await session.commit_transaction()

                    except Exception as e:
                        # Abort transaction in case of any errors
                        await session.abort_transaction()
                        print(f"Transaction aborted due to error: {e}")
                        raise
        except Exception as e:
            print(f"Unexpected Error: {e}")
            raise

    async def find_group_chat_for_patient(self, patient_id: str):
        return await self.mongo_store.find_document(
            "chats",
            {
                "is_group": True,
                "participants": {"$elemMatch": {"id": patient_id}},
            },
        )
