from typing import Dict, Optional

from pydantic import BaseModel, Field

from lib.core.types import (FCMNotificationChannelKeyLiteral,
                            FCMNotificationGroupKeyLiteral)


class FCMNotificationInfo(BaseModel):
    title: str = Field(..., description="Title of the FCM notification")
    body: str = Field(..., description="Body content of the FCM notification")
    channel_key: FCMNotificationChannelKeyLiteral = Field(
        ..., description="Channel key for the FCM notification (e.g., 'chat')"
    )
    group_key: FCMNotificationGroupKeyLiteral = Field(
        ...,
        description="Group key for the FCM notification (e.g., 'chat_group')",
    )
    sender_id: Optional[str] = Field(
        None, description="ID of the message sender"
    )
    data: Optional[Dict[str, str]] = Field(
        default_factory=dict,
        description="Additional data to send with the FCM notification",
    )
