from typing import Literal

ProfileTypeLiteral = Literal[
    "patient",
    "care_provider",
]

FitnessReportTypeLiteral = Literal["daily", "weekly", "monthly", "custom"]

SleepReportTypeLiteral = Literal["daily", "weekly", "monthly", "custom"]


FCMNotificationChannelKeyLiteral = Literal[
    "fitness_sync", "chat_messages", "reminders", "alerts", "health_insights", "other"
]

FCMNotificationGroupKeyLiteral = Literal[
    "fitness_group", "chat_group", "reminder_group", "alert_group", "health_insights_group", "other_group"
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
    "sleep",
    "health-tip",
    "other",
    "patient",
    "care-provider",
    "weight-loss-agent",
]

OpenAIModelLiteral = Literal[
    "gpt-5.1",
    "gpt-5",
    "gpt-5-nano",
    "gpt-5-mini",  # Best for reliability + reasoning
    "gpt-4o",  # For multimodal (text + image)
    "gpt-4o-mini",  # For speed + cost balance
    "o3-mini",  # Optional: experimental or reasoning-heavy tasks
    "gpt-4.1-mini",
]

GeminiAIModelLiteral = Literal[
    "gemini-1.5-flash",
    "gemini-2.0-flash",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-3-pro-preview",
]

PerplexityAIModelLiteral = Literal["sonar", "sonar-reasoning"]

AIModelProviderLiteral = Literal["openai", "gemini", "perplexity"]

ReportTypeLiteral = Literal[
    "index", "laboratory", "radiology", "eye_or_ophthalmology", "other"
]

DocumentTypeLiteral = Literal["report", "other"]
