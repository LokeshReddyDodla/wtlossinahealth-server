from datetime import datetime
from typing import List, Literal, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl, constr


class ChatParticipantSchema(BaseModel):
    id: str = Field(..., description="UUID of the participant.")
    type: Literal["patient", "care_provider"] = Field(
        ...,
        description="Type of the participant, either 'patient' or 'care_provider'.",
    )


class MediaSchema(BaseModel):
    type: Literal["image", "file", "audio"] = Field(
        ..., description="Type of media attached to the message."
    )
    url: HttpUrl = Field(..., description="URL to the media file.")
    caption: Optional[str] = Field(
        None, description="Optional caption for the media."
    )


class MetadataSchema(BaseModel):
    type: Literal["text", "image", "file", "audio"] = Field(
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


class ChatMessageBase(BaseModel):
    sender: ChatParticipantSchema = Field(
        ..., description="Information about the sender."
    )
    receiver: Optional[ChatParticipantSchema] = Field(
        ..., description="Information about the receiver."
    )
    content: str = Field(..., description="Text content of the message.")
    media: Optional[MediaSchema] = Field(
        None, description="Optional media attached to the message."
    )
    reply_to: Optional[str] = Field(
        None, description="UUID of the message being replied to."
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp of the message creation.",
    )
    metadata: MetadataSchema = Field(
        ..., description="Metadata of the message including type and status."
    )
    read_receipts: List[ReadReceiptSchema] = Field(
        default_factory=list,
        description="List of read receipts for the message.",
    )
    severity: Literal["low", "medium", "high", "urgent"] = Field(
        "low", description="Severity or priority of the message."
    )
    is_flagged: bool = Field(
        False,
        description="Indicates if the message is flagged for any reason.",
    )

    class Config:
        schema_extra = {
            "example": {
                "sender": {
                    "id": "456e7890-e12b-34d5-a678-526315178001",
                    "type": "patient",
                    "is_read_only": False,
                    "is_muted": False,
                    "is_archived": False,
                    "joined_at": "2024-09-08T12:00:00Z",
                },
                "receiver": {
                    "id": "789e1234-e56b-78c9-d012-345678901234",
                    "type": "care_provider",
                    "is_read_only": True,
                    "is_muted": True,
                    "is_archived": False,
                    "joined_at": "2024-09-08T12:00:00Z",
                },
                "content": "Hello, this is a test message.",
                "media": {
                    "type": "image",
                    "url": "https://example.com/path-to-image.jpg",
                    "caption": "Check out this image!",
                },
                "reply_to": "123e4567-e89b-12d3-a456-426614174002",
                "timestamp": "2024-09-08T12:34:56Z",
                "metadata": {"type": "text", "status": "sent"},
                "read_receipts": [
                    {
                        "reader_id": "789e4567-e89b-12d3-a456-426614174003",
                        "read_at": "2024-09-08T12:35:56Z",
                    }
                ],
                "severity": "low",
                "is_flagged": False,
            }
        }


class ChatMessage(ChatMessageBase):
    message_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Message ID.",
    )
    pass


class ChatMessageCreate(ChatMessageBase):
    pass
