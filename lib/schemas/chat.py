from datetime import datetime
from typing import Dict, List, Literal, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field

from lib.core.types import ChatKindLiteral, ProfileTypeLiteral
from lib.schemas.chat_message import ChatMessage


class ParticipantSchema(BaseModel):
    id: str = Field(..., description="UUID of the participant.")
    type: ProfileTypeLiteral = Field(
        ...,
        description="Type of the participant, either 'patient' or 'care_provider'.",
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
    is_pinned: Optional[bool] = Field(
        False, description="Whether the participant has pinned this chat."
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
    is_group: Optional[bool] = Field(
        True, description="Indicates this is a group chat."
    )
    kind: ChatKindLiteral = Field(
        "direct",
        description="What this chat is. 'direct' or 'group' is regular "
        "patient/provider messaging; 'support' is a support ticket "
        "conversation managed by the support_tickets layer.",
    )
    alias_name: Optional[str] = Field(
        ...,
        description="Name for the chat, either participant's name or group name",
    )
    alias_profile_picture: Optional[str] = Field(
        None,
        description="Profile picture URL for the chat, either participant's or group",
    )
    description: Optional[str] = Field(
        None,
        description="Optional description for the chat. Primarily used for group chats.",
    )
    participants: List[ParticipantSchema] = Field(
        ..., description="List of participants in the group chat."
    )
    created_at: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when the group chat was created.",
    )
    updated_at: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when the group chat was last updated.",
    )

    last_message: Optional[str] = Field(
        None, description="ID of the last message in the chat."
    )

    unread_counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Map of user IDs to their unread message counts in the chat.",
    )

    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "id": "a7fdfcc9-eff2-4387-8e14-8a057e0de8f9",
                "is_group": True,
                "alias_name": "Diabetes Care Team",
                "alias_profile_picture": "https://example.com/group-pic.png",
                "description": "A group chat for discussing diabetes care management.",
                "participants": [
                    {
                        "id": "9b2ce9b7-93f3-4ce7-aee5-e5799a713a28",
                        "type": "patient",
                        "is_read_only": False,
                        "is_muted": False,
                        "is_archived": False,
                        "joined_at": "2024-09-08T12:00:00Z",
                    },
                    {
                        "id": "23cf94a7-0469-4379-b5f2-174376ac8049",
                        "type": "care_provider",
                        "is_read_only": False,
                        "is_muted": True,
                        "is_archived": False,
                        "joined_at": "2024-09-08T12:05:00Z",
                    },
                ],
                "created_at": "2024-09-08T12:00:00Z",
                "updated_at": "2024-09-08T12:00:00Z",
                "last_message_id": "msg_12345",
                "unread_counts": {
                    "9b2ce9b7-93f3-4ce7-aee5-e5799a713a28": 0,
                    "23cf94a7-0469-4379-b5f2-174376ac8049": 2,
                },
            }
        }


class ChatSchema(ChatSchemaBase):
    pass
