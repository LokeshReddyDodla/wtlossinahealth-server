from typing import Literal

ProfileTypeLiteral = Literal[
    "patient",
    "care_provider",
    "admin",
]

ChatKindLiteral = Literal["direct", "group", "support"]

# Language the AI responds in — ANY valid BCP-47 tag the user picks; the
# LLM translator is generic and the fidelity guards (numbers/markers) are
# language-agnostic, so the server never limits the picker. Validation is
# structural (is it a real language tag?), not a membership whitelist.
# hi/hi-Latn have dedicated eval coverage; other languages ride the same
# guarded path with the English toggle as the safety net.
DEFAULT_AI_LANGUAGE = "en"

# Curated prompt descriptors where the plain language name isn't enough.
# Script/style only — register lives in RESPECTFUL_REGISTER_INSTRUCTION,
# which applies to every language, not a curated few.
_AI_LANGUAGE_OVERRIDES: dict[str, str] = {
    "en": "English",
    "hi": "Hindi (Devanagari script)",
    "hi-Latn": "Hinglish (Hindi in roman script, everyday texting style)",
}

# Universal register rule for any generated or translated patient-facing text.
# Language-agnostic on purpose: every language with a T–V distinction (Hindi
# aap/tu, Bengali apni/tui, Urdu aap/tum, ...) must land on the respectful
# form, including languages nobody on the team can review — models read
# "casual" in a prompt as license for the intimate form.
RESPECTFUL_REGISTER_INSTRUCTION = (
    "Address the patient in the language's RESPECTFUL second-person register "
    "— the polite form used with someone you respect (e.g. a client or an "
    "elder) — while staying warm and friendly. NEVER use the intimate or "
    "overly familiar form, in any language."
)


def is_valid_ai_language(code: str) -> bool:
    """Structurally valid, real language tag (e.g. 'en', 'hi-Latn', 'ur')."""
    import langcodes

    try:
        return langcodes.Language.get(code).is_valid()
    except Exception:
        return False


def ai_language_name(code: str) -> str:
    """Human-readable name for prompts ('respond in <name>')."""
    override = _AI_LANGUAGE_OVERRIDES.get(code)
    if override:
        return override
    import langcodes

    try:
        return langcodes.Language.get(code).display_name()
    except Exception:
        return code

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
