from typing import Literal

ProfileTypeLiteral = Literal[
    "patient",
    "care_provider",
]

FitnessReportTypeLiteral = Literal["daily", "weekly", "monthly", "custom"]

SleepReportTypeLiteral = Literal["daily", "weekly", "monthly", "custom"]


FCMNotificationChannelKeyLiteral = Literal["fitness_sync", "chat_messages", "other"]

FCMNotificationGroupKeyLiteral = Literal["fitness_group", "chat_group", "other_group"]

AiConversationRoleLiteral = Literal["system", "human", "ai"]


AiConversationMessageTypeLiteral = Literal[
    "text", "image", "file", "audio", "custom", "markdown"
]

AiConversationTypeLiteral = Literal[
    "smbg",
    "meal",
    "prescription",
    "report",
    "sleep",
    "health-tip",
    "other",
    "care-provider",
]

OpenAIModelLiteral = Literal[
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4-mini",
    "gpt-3.5-turbo",
    "davinci",
    "o3-mini",
    "o1-mini",
]

GeminiAIModelLiteral = Literal[
    "gemini-1.5-flash",
    "gemini-2.0-flash",
]

PerplexityAIModelLiteral = Literal["sonar", "sonar-reasoning"]

AIModelProviderLiteral = Literal["openai", "gemini", "perplexity"]
