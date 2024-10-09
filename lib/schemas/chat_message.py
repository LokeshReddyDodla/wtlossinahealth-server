from datetime import datetime
from typing import List, Literal, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl, constr


class MediaSchema(BaseModel):
    type: Literal["image", "file", "audio"] = Field(
        ..., description="Type of media attached to the message."
    )
    url: HttpUrl = Field(..., description="URL to the media file.")
    caption: Optional[str] = Field(
        None, description="Optional caption for the media."
    )


class MetadataSchema(BaseModel):
    type: Literal["text", "image", "file", "audio", "custom"] = Field(
        ..., description="Type of the message content."
    )
    status: Literal["sent", "delivered", "read"] = Field(
        ..., description="Status of the message delivery."
    )


class ReadReceiptSchema(BaseModel):
    reader_id: str = Field(..., description="UUID of the reader.")
    read_at: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when the message was read.",
    )


class ReactionSchema(BaseModel):
    user_id: str = Field(..., description="UUID of the user reacting.")
    reaction: str = Field(..., description="Type of reaction (emoji or text).")


class ChatMessageBase(BaseModel):
    id: str = Field(
        default_factory=lambda: str(uuid4()),
        alias="_id",
        description="Unique identifier for the message.",
    )
    chat_id: str = Field(
        ..., description="UUID of the chat this message belongs to."
    )
    sender_id: str = Field(
        ..., description="UUID of the user who sent the message."
    )
    content: str = Field(..., description="Text content of the message.")
    media: Optional[MediaSchema] = Field(
        None, description="Optional media attached to the message."
    )
    reply_to: Optional[str] = Field(
        None, description="UUID of the message being replied to."
    )
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp of the message creation.",
    )
    updated_at: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp of the last update (e.g., for reactions or edits).",
    )
    metadata: MetadataSchema = Field(
        ..., description="Metadata of the message including type and status."
    )
    read_receipts: List[ReadReceiptSchema] = Field(
        default_factory=list,
        description="List of read receipts for the message.",
    )
    reactions: List[ReactionSchema] = Field(
        default_factory=list,
        description="List of reactions to the message.",
    )
    severity: Literal["low", "medium", "high", "urgent"] = Field(
        "low", description="Severity or priority of the message."
    )
    is_flagged: bool = Field(
        False,
        description="Indicates if the message is flagged for any reason.",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "_id": "msg_12345",
                "chat_id": "chat_a7fdfcc9-eff2-4387-8e14-8a057e0de8f9",
                "sender_id": "456e7890-e12b-34d5-a678-526315178001",
                "content": "Hello, this is a test message.",
                "media": {
                    "type": "image",
                    "url": "https://example.com/path-to-image.jpg",
                    "caption": "Check out this image!",
                },
                "reply_to": "123e4567-e89b-12d3-a456-426614174002",
                "timestamp": "2024-09-08T12:34:56Z",
                "updated_at": "2024-09-08T12:35:56Z",
                "metadata": {"type": "text", "status": "sent"},
                "read_receipts": [
                    {
                        "reader_id": "789e4567-e89b-12d3-a456-426614174003",
                        "read_at": "2024-09-08T12:35:56Z",
                    }
                ],
                "reactions": [
                    {
                        "user_id": "789e4567-e89b-12d3-a456-426614174003",
                        "reaction": "👍",
                    }
                ],
                "severity": "low",
                "is_flagged": False,
            }
        }


class ChatMessage(ChatMessageBase):
    pass


class ChatMessageCreate(ChatMessageBase):
    pass
