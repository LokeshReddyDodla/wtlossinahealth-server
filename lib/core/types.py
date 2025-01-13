from typing import Literal

ProfileTypeLiteral = Literal[
    "patient",
    "care_provider",
]

FitnessReportTypeLiteral = Literal["daily", "weekly", "monthly", "custom"]


FCMNotificationChannelKeyLiteral = Literal[
    "fitness_sync", "chat_messages", "other"
]

FCMNotificationGroupKeyLiteral = Literal[
    "fitness_group", "chat_group", "other_group"
]

AiConversationRoleLiteral = Literal["system", "human", "ai"]


AiConversationMessageTypeLiteral = Literal[
    "text", "image", "file", "audio", "custom", "markdown"
]

AiConversationTypeLiteral = Literal[
    "smbg",
    "meal",
    "prescription",
    "report",
    "health-tip",
    "other",
]

OpenAIModelLiteral = Literal[
    "gpt-4o", "gpt-4o-mini", "gpt-4-mini", "gpt-3.5-turbo", "davinci"
]
