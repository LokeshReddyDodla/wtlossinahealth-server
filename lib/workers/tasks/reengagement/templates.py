"""Re-engagement notification templates — tiered by inactivity duration."""

from __future__ import annotations

from enum import Enum
from string import Template


class ReengagementTier(str, Enum):
    GENTLE = "gentle"        # 7-13 days inactive
    NUDGE = "nudge"          # 14-21 days inactive
    LAST_CALL = "last_call"  # 22-30 days inactive


# Each tier has multiple variants to avoid staleness across attempts.
# Templates use $name (first name) and $days (days since last activity).

_TEMPLATES: dict[ReengagementTier, list[tuple[str, str]]] = {
    ReengagementTier.GENTLE: [
        (
            "We miss you, $name!",
            "It's been $days days since your last check-in. Your health data is ready whenever you are!",
        ),
        (
            "Hey $name, how are you?",
            "We noticed it's been $days days. Even a quick log helps us keep track of your health trends!",
        ),
        (
            "Your health journey awaits, $name",
            "It's been $days days — a quick check-in today keeps your insights fresh and your progress on track!",
        ),
    ],
    ReengagementTier.NUDGE: [
        (
            "$name, your trends are waiting",
            "It's been $days days — your health insights are ready to explore. Even a quick check-in helps you stay on track!",
        ),
        (
            "Quick update for you, $name",
            "$days days since your last visit. Your health data doesn't stop — come see what's new and keep your momentum going!",
        ),
        (
            "Don't lose your progress, $name",
            "It's been $days days. Your health trends are still being tracked — open the app to see where you stand!",
        ),
    ],
    ReengagementTier.LAST_CALL: [
        (
            "Still here for you, $name",
            "It's been $days days since we connected. One quick check-in can restart your health momentum!",
        ),
        (
            "We haven't forgotten you, $name",
            "$days days is a while! Your health data is safe and waiting. A single tap gets you back on track.",
        ),
        (
            "One step is all it takes, $name",
            "It's been $days days. We're still tracking your health — come back and see how you're doing!",
        ),
    ],
}


def get_tier(days_inactive: int) -> ReengagementTier | None:
    """Determine the re-engagement tier from days of inactivity.

    Returns None if outside the 7-30 day window.
    """
    if 7 <= days_inactive <= 13:
        return ReengagementTier.GENTLE
    if 14 <= days_inactive <= 21:
        return ReengagementTier.NUDGE
    if 22 <= days_inactive <= 30:
        return ReengagementTier.LAST_CALL
    return None


def get_message(tier: ReengagementTier, name: str, days: int, attempt: int) -> tuple[str, str]:
    """Return (title, body) for a re-engagement notification.

    Rotates through variants based on attempt number to avoid repeating
    the exact same message.
    """
    variants = _TEMPLATES[tier]
    idx = (attempt - 1) % len(variants)
    title_tpl, body_tpl = variants[idx]
    return (
        Template(title_tpl).safe_substitute(name=name, days=days),
        Template(body_tpl).safe_substitute(name=name, days=days),
    )
