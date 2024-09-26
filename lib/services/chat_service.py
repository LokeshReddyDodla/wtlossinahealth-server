from datetime import datetime
from typing import Awaitable, Callable, List, Literal, Optional

from faker import Faker
from fastapi import Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pymongo.errors import OperationFailure, PyMongoError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.core.constants import PROFILE_TYPE_CARE_PROVIDER, PROFILE_TYPE_PATIENT
from lib.core.mongo_store import get_mongo_store
from lib.core.types import ProfileType
from lib.dependencies.database import get_postgres_session
from lib.models.patient_care_provider import \
    PatientCareProvider as PatientCareProviderModel
from lib.pipelines.chat_pipelines import (get_user_chat_pipeline,
                                          get_user_messages_pipeline)
from lib.schemas.chat import ChatSchema, ParticipantSchema
from lib.schemas.chat_message import ChatMessage, ChatMessageCreate

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

    async def fetch_user_chats(
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
            patient_profile_service = PatientProfileService(
                postgres_session, self
            )
            patient_profiles = (
                await patient_profile_service.fetch_patient_profiles(
                    list(patient_ids)
                )
            )

            # Fetch profiles for care providers from PostgreSQL
            care_provider_profile_service = CareProviderService(
                postgres_session, self
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

                for receiver in chat.get("receivers", []):
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

    async def fetch_user_messages(
        self, user_id: str, last_sync_time: Optional[datetime] = None
    ):
        """
        Fetch all messages for a specific user based on user_id.
        """
        try:
            pipeline = get_user_messages_pipeline(user_id, last_sync_time)
            messages = (
                await self.mongo_store.db["chats"]
                .aggregate(pipeline)
                .to_list(length=None)
            )
            return messages

        except PyMongoError as e:
            print(f"MongoDB Error: {e}")
            raise

    async def add_message(self, message_data: ChatMessageCreate):
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
            read_receipts=[],
            reactions=[],
        )
        message_dict = message.dict(by_alias=True)

        try:
            # Insert the message into the chat_messages collection
            await self.mongo_store.insert_document(
                "chat_messages", message_dict
            )
            print(
                f"Message {message.id} added to chat {message_data.chat_id}."
            )

            # Update the chat's last_message and updated_at fields
            await self.mongo_store.db["chats"].update_one(
                {"_id": message_data.chat_id},
                {
                    "$set": {
                        "last_message": message.id,
                        "updated_at": datetime.now(),
                    },
                    "$inc": {
                        f"unread_counts.{message_data.sender_id}": 0
                    },  # Sender unread count remains 0
                },
            )

            # Increment unread counts for other participants in the chat
            chat = await self.mongo_store.db["chats"].find_one(
                {"_id": message_data.chat_id}
            )
            if chat:
                for participant in chat["participants"]:
                    participant_id = participant["id"]
                    if participant_id != message_data.sender_id:
                        # Increment the unread count for this participant
                        await self.mongo_store.db["chats"].update_one(
                            {"_id": message_data.chat_id},
                            {"$inc": {f"unread_counts.{participant_id}": 1}},
                        )

            # After message is added to DB, we use the utility function to emit it to all participants
            await self.emit_to_associated_participants(
                message_key="newMessage",
                data=jsonable_encoder(message_dict),
                chat_id=message_data.chat_id,
            )

            print(
                f"Message {message.id} broadcasted to all participants in chat {message_data.chat_id}."
            )

        except Exception as e:
            print(f"Failed to add message: {str(e)}")
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

    async def toggle_pin_chat(self, chat_id: str, participant_id: str):
        try:
            from lib.services.socketio_service import sio

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

    async def mark_all_messages_as_read(self, chat_id: str, user_id: str):
        try:
            # Update all messages in this chat by adding the user to the read_receipts
            await self.mongo_store.db["chat_messages"].update_many(
                {
                    "chat_id": chat_id,
                    "read_receipts.reader_id": {"$ne": user_id},
                },
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

            # Set unread count for this user to 0 in the chat
            await self.mongo_store.db["chats"].update_one(
                {"_id": chat_id},
                {
                    "$set": {
                        f"unread_counts.{user_id}": 0,
                        "updated_at": datetime.now(),
                    }
                },
            )

        except Exception as e:
            print(f"Failed to mark all messages as read: {str(e)}")
            raise Exception(f"Failed to mark all messages as read: {str(e)}")

    async def mark_message_as_read(
        self, chat_id: str, user_id: str, message_id: str
    ):
        """
        Mark a specific message in a chat as read by the user.
        """
        try:
            # Update the specific message by adding the user to the read_receipts

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

            # Check if there are no unread messages left for this user and update the unread count
            unread_message_count = await self.mongo_store.db[
                "chat_messages"
            ].count_documents(
                {"chat_id": chat_id, "read_receipts": {"$ne": user_id}}
            )

            # If no more unread messages, set unread count to 0 for this user
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

        except Exception as e:
            print(f"Failed to mark message as read: {str(e)}")
            raise Exception(f"Failed to mark message as read: {str(e)}")

    async def toggle_reaction(
        self, chat_id: str, message_id: str, user_id: str, reaction: str
    ):
        try:
            # Fetch the message to check the current reactions
            message = await self.mongo_store.db["chat_messages"].find_one(
                {"_id": message_id, "chat_id": chat_id}
            )

            if not message:
                raise Exception(
                    f"Message {message_id} not found in chat {chat_id}"
                )

            # Check if the user has already reacted to this message
            user_reaction = next(
                (
                    r
                    for r in message.get("reactions", [])
                    if r["user_id"] == user_id
                ),
                None,
            )

            current_time = datetime.now()

            if user_reaction:
                # If the user already reacted with the same reaction, remove the reaction (toggle off)
                if user_reaction["reaction"] == reaction:
                    await self.mongo_store.db["chat_messages"].update_one(
                        {"_id": message_id, "chat_id": chat_id},
                        {
                            "$pull": {"reactions": {"user_id": user_id}},
                            "$set": {"updated_at": current_time},
                        },
                    )
                    print(
                        f"Removed reaction {reaction} from message {message_id} by user {user_id}"
                    )

                # If the user reacted with a different reaction, update it
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
                    print(
                        f"Updated reaction to {reaction} on message {message_id} by user {user_id}"
                    )
            else:
                # If no reaction exists, add the new reaction
                await self.mongo_store.db["chat_messages"].update_one(
                    {"_id": message_id, "chat_id": chat_id},
                    {
                        "$addToSet": {
                            "reactions": {
                                "user_id": user_id,
                                "reaction": reaction,
                            }
                        },
                        "$set": {"updated_at": current_time},
                    },
                )
                print(
                    f"Added reaction {reaction} to message {message_id} by user {user_id}"
                )

        except Exception as e:
            print(f"Failed to toggle reaction: {str(e)}")
            raise Exception(f"Failed to toggle reaction: {str(e)}")

    async def get_message_by_id(self, message_id: str):
        try:
            message = await self.mongo_store.db["chat_messages"].find_one(
                {"_id": message_id},
            )
            if not message:
                raise Exception(f"Message {message_id} not found in chat ")
            return jsonable_encoder(message)
        except Exception as e:
            print(f"Failed to fetch message reactions: {str(e)}")
            raise Exception(f"Failed to fetch message reactions: {str(e)}")

    async def fetch_chat_participants(self, chat_id: str) -> List[dict]:
        """Fetch participants using chat_id."""
        chat = await self.mongo_store.db["chats"].find_one(
            {"_id": chat_id}, {"participants": 1}
        )
        if not chat:
            raise Exception(f"Chat with ID {chat_id} not found")
        return chat.get("participants", [])

    async def fetch_associated_participants(
        self,
        session: AsyncSession,
        patient_id: Optional[str] = None,
        care_provider_id: Optional[str] = None,
        patient_care_provider_id: Optional[str] = None,
    ) -> List[dict]:
        """Fetch associated participants using provided identifiers."""
        from lib.services.patient_care_provider_service import \
            PatientCareProviderService

        associated_records = (
            await PatientCareProviderService.fetch_associated_records(
                postgres_session=session,
                patient_id=patient_id,
                care_provider_id=care_provider_id,
                patient_care_provider_id=patient_care_provider_id,
            )
        )
        # Combine patient_id and care_provider_id from associated records
        participants = [
            {"id": record.patient_id} for record in associated_records
        ] + [{"id": record.care_provider_id} for record in associated_records]
        return participants

    async def emit_to_participants(
        self,
        participants: List[dict],
        message_key: str,
        data: Optional[dict] = None,
    ):
        """Emit a message to each participant."""
        from lib.services.socketio_service import sio

        for participant in participants:
            user_id = participant["id"]
            await sio.emit(message_key, data, room=user_id)
            print(f"Emitted {message_key} to participant {user_id}")

    async def emit_to_associated_participants(
        self,
        message_key: str,
        data: Optional[dict] = None,
        chat_id: Optional[str] = None,
        patient_id: Optional[str] = None,
        care_provider_id: Optional[str] = None,
        patient_care_provider_id: Optional[str] = None,
        session: Optional[AsyncSession] = None,
    ):
        try:
            participants = []

            if chat_id:
                participants = await self.fetch_chat_participants(chat_id)
            elif session and (
                patient_id or care_provider_id or patient_care_provider_id
            ):
                participants = await self.fetch_associated_participants(
                    session,
                    patient_id=patient_id,
                    care_provider_id=care_provider_id,
                    patient_care_provider_id=patient_care_provider_id,
                )
            else:
                raise ValueError(
                    "Must provide either chat_id, patient_id, or care_provider_id"
                )

            # Emit the message to participants
            await self.emit_to_participants(participants, message_key, data)

        except Exception as e:
            print(f"Failed to emit {message_key} to participants: {str(e)}")
            raise
