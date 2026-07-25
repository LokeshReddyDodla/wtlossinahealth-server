"""Notification delivery policy — the declarative rulebook the broker enforces.

Every patient-facing push is one of four TIERS. A tier fixes the defaults
(is it rate-limited? does it respect quiet hours? can the patient mute it?);
a per-category entry can override the daily cap. Adding a new notification
type = adding one row here, not wiring a new gate somewhere in the codebase.

    CRITICAL — meds, safety alerts. Unlimited, ignores quiet hours, unmutable,
               bypasses the master notification permission.
    EVENT    — the patient just logged/did something. Unlimited, ignores quiet
               hours, not mutable. Respects the master permission.
    PROACTIVE— unprompted outreach (insights, brief, care-intent nudges,
               re-engagement). Per-category daily cap, quiet hours, mutable.
    SOCIAL   — streaks, achievements, buddy. Separate (small) cap so it can't
               consume the proactive budget. Quiet hours, mutable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class NotificationTier(str, Enum):
    CRITICAL = "critical"
    EVENT = "event"
    PROACTIVE = "proactive"
    SOCIAL = "social"


@dataclass(frozen=True)
class NotificationPolicy:
    tier: NotificationTier
    daily_cap: int | None       # None = unlimited
    respects_quiet_hours: bool
    mutable: bool
    bypass_permission: bool      # send even if the master switch is off


_TIER_DEFAULTS: dict[NotificationTier, NotificationPolicy] = {
    NotificationTier.CRITICAL: NotificationPolicy(
        NotificationTier.CRITICAL, daily_cap=None, respects_quiet_hours=False,
        mutable=False, bypass_permission=True,
    ),
    NotificationTier.EVENT: NotificationPolicy(
        NotificationTier.EVENT, daily_cap=None, respects_quiet_hours=False,
        mutable=False, bypass_permission=False,
    ),
    NotificationTier.PROACTIVE: NotificationPolicy(
        NotificationTier.PROACTIVE, daily_cap=3, respects_quiet_hours=True,
        mutable=True, bypass_permission=False,
    ),
    NotificationTier.SOCIAL: NotificationPolicy(
        NotificationTier.SOCIAL, daily_cap=2, respects_quiet_hours=True,
        mutable=True, bypass_permission=False,
    ),
}

# Category → tier. The category string is what the caller passes and what the
# per-patient mute preference is keyed on, so it must be stable and specific.
_CATEGORY_TIER: dict[str, NotificationTier] = {
    # Critical — the unmutable floor
    "medication_reminder": NotificationTier.CRITICAL,
    "medication_dose": NotificationTier.CRITICAL,
    "medication_lifecycle": NotificationTier.CRITICAL,
    "refill_reminder": NotificationTier.CRITICAL,
    "prescription": NotificationTier.CRITICAL,
    "safety_alert": NotificationTier.CRITICAL,
    "follow_up_reminder": NotificationTier.CRITICAL,
    # Event — reactive, patient is present
    "meal_logged": NotificationTier.EVENT,
    "smbg_logged": NotificationTier.EVENT,
    "symptom_logged": NotificationTier.EVENT,
    "cgm_threshold_crossed": NotificationTier.EVENT,
    "medication_missed": NotificationTier.EVENT,
    # Proactive — unprompted health outreach
    "proactive_insight": NotificationTier.PROACTIVE,
    "daily_brief": NotificationTier.PROACTIVE,
    "care_intent_nudge": NotificationTier.PROACTIVE,
    "re_engagement": NotificationTier.PROACTIVE,
    # Social — gamification
    "gamification": NotificationTier.SOCIAL,
    "streak_reminder": NotificationTier.SOCIAL,
}

# Per-category cap overrides (else the tier default applies).
_CATEGORY_CAP: dict[str, int] = {
    "re_engagement": 1,        # at most one nudge/day on top of the ≤3 insight cap
    "care_intent_nudge": 2,    # provider asks get their own room within proactive
}


def policy_for(category: str) -> NotificationPolicy:
    """Resolve the delivery policy for a category. Unknown category → PROACTIVE
    (rate-limited, quiet-hours, mutable) — the safe default, never CRITICAL."""
    tier = _CATEGORY_TIER.get(category, NotificationTier.PROACTIVE)
    base = _TIER_DEFAULTS[tier]
    cap = _CATEGORY_CAP.get(category, base.daily_cap)
    if cap == base.daily_cap:
        return base
    return NotificationPolicy(
        base.tier, daily_cap=cap, respects_quiet_hours=base.respects_quiet_hours,
        mutable=base.mutable, bypass_permission=base.bypass_permission,
    )
