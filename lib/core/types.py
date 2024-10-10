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

ConversationRoleLiteral = Literal["system", "human", "ai"]

ConversationTypeLiteral = Literal[
    "meal_analysis", "prescription_analysis", "report_analysis"
]

ConversationMessageTypeLiteral = Literal[
    "text", "image", "file", "audio", "custom", "markdown"
]

OpenAIModelLiteral = Literal[
    "gpt-4o", "gpt-4o-mini", "gpt-4-mini", "gpt-3.5-turbo", "davinci"
]
