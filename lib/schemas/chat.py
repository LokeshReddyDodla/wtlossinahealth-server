from datetime import datetime
from typing import List, Literal, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl, constr

from lib.schemas.chat_message import ChatMessage


class ParticipantSchema(BaseModel):
    id: str = Field(..., description="UUID of the participant.")
    type: Literal["patient", "care_provider"] = Field(
        ...,
        description="Type of the participant, either 'patient' or 'care_provider'.",
    )
    name: str = Field(..., description="Name of the participant.")
    profile_picture: Optional[str] = Field(
        None, description="URL of the participant's profile picture."
    )
    is_read_only: Optional[bool] = Field(
        False,
        description="Whether the participant can only read messages but not send them.",
    )
    is_muted: Optional[bool] = Field(
        False,
        description="Whether notifications are muted for the participant.",
    )
    is_archived: Optional[bool] = Field(
        False, description="Whether the participant has archived this chat."
    )
    joined_at: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when the participant joined the chat.",
    )


class ChatSchemaBase(BaseModel):
    id: str = Field(
        default_factory=lambda: str(uuid4()),
        alias="_id",
        description="Chat ID.",
    )
    participants: List[ParticipantSchema] = Field(
        ..., description="List of participants in the group chat."
    )
    messages: List[ChatMessage] = Field(
        default_factory=list, description="List of messages in the group chat."
    )
    created_at: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when the group chat was created.",
    )
    updated_at: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when the group chat was last updated.",
    )

    class Config:
        allow_population_by_field_name = True
        schema_extra = {
            "example": {
                "id": "a7fdfcc9-eff2-4387-8e14-8a057e0de8f9",
                "is_group": True,
                "participants": [
                    {
                        "id": "9b2ce9b7-93f3-4ce7-aee5-e5799a713a28",
                        "type": "patient",
                        "name": "Dr. Mukhtar Test",
                        "profile_picture": "https://example.com/path-to-image.jpg",
                        "is_read_only": False,
                        "is_muted": False,
                        "is_archived": False,
                        "joined_at": "2024-09-08T12:00:00Z",
                    }
                ],
                "messages": [],
                "created_at": "2024-09-08T12:00:00Z",
                "updated_at": "2024-09-08T12:00:00Z",
            }
        }


class GroupChatSchema(ChatSchemaBase):
    is_group: Optional[bool] = Field(True, description="Indicates this is a group chat.")


class IndividualChatSchema(ChatSchemaBase):
    is_group: bool = Field(
        False, description="Indicates this is an individual chat."
    )
