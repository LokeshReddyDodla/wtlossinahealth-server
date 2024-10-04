from typing import Dict, Optional

from pydantic import BaseModel, Field


class FCMNotificationInfo(BaseModel):
    title: str = Field(..., description="Title of the FCM notification")
    body: str = Field(..., description="Body content of the FCM notification")
    append_name: bool = Field(
        False,
        description="Flag to append sender's name to the notification title",
    )
    channel_id: str = Field(
        ..., description="Channel id for the FCM notification (e.g., 'chat')"
    )
    sender_id: Optional[str] = Field(
        None, description="ID of the message sender"
    )
    data: Optional[Dict[str, str]] = Field(
        default_factory=dict,
        description="Additional data to send with the FCM notification",
    )
