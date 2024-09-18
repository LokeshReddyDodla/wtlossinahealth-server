from datetime import datetime
from typing import List, Literal, Optional

from pymongo.errors import OperationFailure, PyMongoError

from lib.core.mongo_store import get_mongo_store
from lib.pipelines.chat_pipelines import get_chat_pipeline
from lib.schemas.chat import ChatSchema, ParticipantSchema
from lib.schemas.chat_message import ChatMessage, ChatMessageCreate
from lib.services.socketio_service import sio
from lib.utils.serializers import serialize_message


class ChatService:
    def __init__(self):
        self.mongo_store = get_mongo_store()

    async def create_new_chat(
        self,
        user_id: str,
        type: Literal["patient", "care_provider"],
        is_group: bool,
        is_read_only: Optional[bool] = False,
        is_muted: Optional[bool] = False,
        is_archived: Optional[bool] = False,
    ):
        participant = ParticipantSchema(
            id=user_id,
            type=type,
            is_read_only=is_read_only,
            is_muted=is_muted,
            is_archived=is_archived,
        )

        # Initialize unread_counts for each participant
        unread_counts = {participant.id: 0}

        chat = ChatSchema(
            is_group=is_group,
            participants=[participant],
            last_message=None,
            unread_counts=unread_counts,
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

        chat = ChatSchema(
            is_group=is_group,
            participants=participants,
            last_message=None,
            unread_counts=unread_counts,
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
        type: Literal["patient", "care_provider"],
        is_read_only: Optional[bool] = False,
        is_muted: Optional[bool] = False,
        is_archived: Optional[bool] = False,
    ):
        participant = ParticipantSchema(
            id=user_id,
            type=type,
            is_read_only=is_read_only,
            is_muted=is_muted,
            is_archived=is_archived,
        )
        participant_dict = participant.dict()

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

    async def add_message(
        self,
        chat_id: str,
        message_data: ChatMessageCreate,
    ):
        message = ChatMessage(
            chat_id=chat_id,
            sender_id=message_data.sender_id,
            content=message_data.content,
            media=message_data.media,
            reply_to=message_data.reply_to,
            timestamp=message_data.timestamp,
            metadata=message_data.metadata,
            severity=message_data.severity or "low",
            is_flagged=message_data.is_flagged or False,
        )
        message_dict = message.dict()

        try:
            await self.mongo_store.insert_document(
                "chat_messages", message_dict
            )
            print(f"Message {message.id} added to chat {chat_id}.")

            # Update the chat document's last_message_id and updated_at fields
            await self.mongo_store.db["chats"].update_one(
                {"id": chat_id},
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
                    "message",
                    {
                        "room": chat_id,
                        "message": serialize_message(message_dict),
                    },
                    room=chat_id,
                )
                print(f"Message {message.id} broadcasted to room {chat_id}.")
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
