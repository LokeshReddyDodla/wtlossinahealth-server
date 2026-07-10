from typing import Literal

ProfileTypeLiteral = Literal[
    "patient",
    "care_provider",
    "admin",
]

ChatKindLiteral = Literal["direct", "group", "support"]

# Language the AI responds in. "hi-Latn" = Hinglish (roman-script Hindi).
# Adding a language = new value here + translation eval pass.
AiLanguageLiteral = Literal["en", "hi", "hi-Latn"]
AI_LANGUAGES: tuple[str, ...] = ("en", "hi", "hi-Latn")
DEFAULT_AI_LANGUAGE = "en"

# Human-readable names used in prompts ("respond in <name>").
AI_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "hi": "Hindi (Devanagari script)",
    "hi-Latn": "Hinglish (Hindi in roman script, casual conversational)",
}

SupportScopeLiteral = Literal["product", "facility"]

SupportTicketStatusLiteral = Literal["open", "pending", "resolved", "closed"]

FitnessReportTypeLiteral = Literal["daily", "weekly", "monthly", "custom"]

SleepReportTypeLiteral = Literal["daily", "weekly", "monthly", "custom"]


FCMNotificationChannelKeyLiteral = Literal[
    "fitness_sync",
    "chat_messages",
    "support_messages",
    "reminders",
    "alerts",
    "health_insights",
    "gamification",
    "other",
]

FCMNotificationGroupKeyLiteral = Literal[
    "fitness_group",
    "chat_group",
    "support_group",
    "reminder_group",
    "alert_group",
    "health_insights_group",
    "gamification_group",
    "other_group",
]

NotificationCategoryLiteral = Literal[
    "gamification",
    "medication_lifecycle",
    "medication_refill",
    "medication_dose",
    "follow_up",
]

NotificationSeverityLiteral = Literal["info", "warning", "alert"]

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
