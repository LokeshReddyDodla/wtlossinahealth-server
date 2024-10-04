from typing import Literal

ProfileTypeLiteral = Literal[
    "patient",
    "care_provider",
]

FCMNotificationChannelKeyLiteral = Literal[
    "fitness_sync", "chat_messages", "other"
]

FCMNotificationGroupKeyLiteral = Literal[
    "fitness_group", "chat_group", "other_group"
]
