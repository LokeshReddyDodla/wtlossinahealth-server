"""Daily notification budget — prevents notification fatigue.

Health-critical notifications (medication, refill, follow-up, prescription changes)
always send. Lower-priority notifications (insights, streaks, re-engagement) are
capped at DAILY_CAP per patient per day.
"""

from datetime import date

from lib.core.cache_store import CacheStore

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

_cache = CacheStore("notif_budget")


def can_send(patient_id: str, notification_type: str) -> bool:
    if notification_type in ALWAYS_SEND:
        return True
    key = f"{patient_id}:{date.today().isoformat()}"
    count = _cache.get_key(key)
    return int(count or 0) < DAILY_CAP


def record_sent(patient_id: str) -> None:
    key = f"{patient_id}:{date.today().isoformat()}"
    _cache.incr_key(key)
    _cache.expire_key(key, 86400)
