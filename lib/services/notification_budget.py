"""Daily notification budget — prevents notification fatigue.

Health-critical notifications (medication, refill, follow-up, prescription changes)
always send. Lower-priority notifications (insights, streaks, re-engagement) are
capped at DAILY_CAP per patient per day.
"""

from datetime import date

DAILY_CAP = 8

ALWAYS_SEND = frozenset({
    "medication_reminder",
    "refill_reminder",
    "follow_up_reminder",
    "prescription_confirmed",
    "prescription_edited",
    "medication_paused",
    "medication_resumed",
    "medication_discontinued",
    "medication_activated",
})

_cache = None


def _get_cache():
    global _cache
    if _cache is None:
        from lib.core.cache_store import CacheStore
        _cache = CacheStore("notif_budget")
    return _cache


def can_send(patient_id: str, notification_type: str) -> bool:
    if notification_type in ALWAYS_SEND:
        return True
    try:
        key = f"{patient_id}:{date.today().isoformat()}"
        count = _get_cache().get_key(key)
        return int(count or 0) < DAILY_CAP
    except Exception:
        return True  # if Redis is down, don't block notifications


def record_sent(patient_id: str) -> None:
    try:
        key = f"{patient_id}:{date.today().isoformat()}"
        _get_cache().incr_key(key)
        _get_cache().expire_key(key, 86400)
    except Exception:
        pass  # best-effort — don't crash if Redis is down
