"""Per-category, patient-local daily notification budget (async Redis).

Replaces the old single blind 8/day counter. Each category counts against its
OWN key, so critical medication reminders can never drain the room a patient's
proactive insights need, and chatty gamification can never starve either. The
day boundary is the PATIENT's local day, not the server's.

Fail-open: if Redis is unavailable, never block a notification.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from lib.ai_foundation.config import settings

logger = logging.getLogger(__name__)

_cache = None


def _get_cache():
    global _cache
    if _cache is None:
        from lib.core.cache_store import CacheStore
        _cache = CacheStore("notif_budget")
    return _cache


def _local_day(tz_name: str | None) -> str:
    try:
        tz = ZoneInfo(tz_name or settings.DEFAULT_PATIENT_TIMEZONE)
    except Exception:
        tz = ZoneInfo(settings.DEFAULT_PATIENT_TIMEZONE)
    return datetime.now(tz).date().isoformat()


def _key(patient_id: str, category: str, tz_name: str | None) -> str:
    return f"{patient_id}:{category}:{_local_day(tz_name)}"


async def under_cap(patient_id: str, category: str, cap: int, tz_name: str | None) -> bool:
    """True if this category is still under its daily cap for the patient's
    local day. ``cap is None`` (unlimited) always returns True."""
    if cap is None:
        return True
    try:
        raw = await _get_cache().aget_key(_key(patient_id, category, tz_name))
        return int(raw or 0) < cap
    except Exception:
        return True  # Redis down — don't block


async def record_sent(patient_id: str, category: str, tz_name: str | None) -> None:
    """Increment the per-category counter (TTL 2 days covers any tz)."""
    try:
        key = _key(patient_id, category, tz_name)
        await _get_cache().aincr_key(key)
        await _get_cache().aexpire_key(key, 172_800)
    except Exception:
        pass  # best-effort
