"""Notification Broker — the single choke point every patient push flows through.

One place owns the full delivery decision, driven by the declarative policy in
policy.py:

    resolve policy → mute check → permission check → quiet-hours →
    per-category budget → translate → persist inbox row → FCM → record budget

A new notification type is a new policy row (policy.py), not a new gate here.

Insights and notifications use separate stores: only notifications are filed
as inbox rows; insights route through for the delivery decision but pass
record_inbox=False.

Infra errors (Redis/DB down) fail open toward delivery; explicit patient
choices (mute, permission) fail closed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from lib.core.container import container
from lib.core.postgres_store import PostgresStore
from lib.core.types import (
    DEFAULT_AI_LANGUAGE,
    FCMNotificationChannelKeyLiteral,
    FCMNotificationGroupKeyLiteral,
)
from lib.services.notifications import budget as _budget
from lib.services.notifications.policy import policy_for

logger = logging.getLogger(__name__)


@dataclass
class DeliveryResult:
    delivered: bool
    reason: str  # "sent" | "muted" | "no_permission" | "quiet_hours" | "over_cap" | "error"
    notification_id: Optional[UUID] = None


async def deliver(
    patient_id: str,
    *,
    category: str,
    title: str,
    body: str,
    channel_key: FCMNotificationChannelKeyLiteral,
    group_key: FCMNotificationGroupKeyLiteral,
    data: Optional[dict[str, Any]] = None,
    severity: Optional[str] = None,
    deeplink: Optional[str] = None,
    body_translation: Optional[str] = None,  # pre-translated body, reused if given
    prelocalized: bool = False,  # title/body already in-language; skip translation
    record_inbox: bool = True,  # False for insights (own store, not the inbox)
    force: bool = False,  # bypass mute/quiet/budget/permission (system sends)
) -> DeliveryResult:
    data = data or {}
    pol = policy_for(category)
    tz_name = await _resolve_timezone(patient_id)

    # 1. Mute — explicit patient choice, fails closed. CRITICAL is unmutable.
    if pol.mutable and not force:
        if await _is_muted(patient_id, category):
            return DeliveryResult(False, "muted")

    # 2. Quiet hours — proactive/social only, patient-local.
    if pol.respects_quiet_hours and not force:
        from lib.ai_foundation.agents.proactive_monitor.scheduling import is_within_scan_window
        if not is_within_scan_window(tz_name):
            return DeliveryResult(False, "quiet_hours")

    # 3. Per-category daily budget, patient-local. daily_cap None = unlimited
    # (CRITICAL/EVENT), never counted.
    if pol.daily_cap is not None and not force:
        if not await _budget.under_cap(patient_id, category, pol.daily_cap, tz_name):
            return DeliveryResult(False, "over_cap")

    # 4. Language — one voice, patient's language, English canonical in code.
    if prelocalized:
        title_out, body_out = title, body
    else:
        title_out, body_out = await _localize(patient_id, title, body, body_translation)

    # 5. Inbox row before FCM, so a failed push still leaves a record.
    # Insights skip this — their record lives in the insight store.
    notif_id = (
        await _persist(patient_id, category, title_out, body_out, severity, deeplink, data)
        if record_inbox else None
    )

    # 6. FCM. CRITICAL bypasses the master permission switch.
    sent = await _send_fcm(
        patient_id, title_out, body_out, channel_key, group_key,
        {**data, "category": category, "notification_id": str(notif_id) if notif_id else ""},
        skip_permission_check=(pol.bypass_permission or force),
    )
    if not sent and not pol.bypass_permission and not force:
        # FCM refused (no permission / no token) — inbox row stays, but don't
        # burn budget on a push the patient never received.
        return DeliveryResult(False, "no_permission", notif_id)

    # 7. Record against the per-category budget (only capped tiers need it).
    if pol.daily_cap is not None:
        await _budget.record_sent(patient_id, category, tz_name)
    return DeliveryResult(True, "sent", notif_id)


# ── internals ────────────────────────────────────────────────────────────────


async def _resolve_timezone(patient_id: str) -> str | None:
    try:
        from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver
        resolver = container.resolve(PatientNameResolver)
        tzs = await resolver.resolve_timezones([patient_id])
        return tzs.get(patient_id)
    except Exception:
        return None


async def _is_muted(patient_id: str, category: str) -> bool:
    """A row with enabled=False means muted. No row = enabled (opt-out)."""
    try:
        from sqlalchemy import select
        from lib.models.patient_notification_preference import PatientNotificationPreference

        store = container.resolve(PostgresStore)
        async with store.get_session() as session:
            pref = await session.scalar(
                select(PatientNotificationPreference).where(
                    PatientNotificationPreference.patient_id == UUID(patient_id),
                    PatientNotificationPreference.category == category,
                )
            )
            return pref is not None and not pref.enabled
    except Exception as exc:
        logger.warning("mute lookup failed for %s/%s: %s", patient_id, category, exc)
        return False  # infra error → don't suppress


async def _localize(patient_id, title, body, body_translation):
    try:
        from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver
        from lib.ai_foundation.translation import TranslationService

        resolver = container.resolve(PatientNameResolver)
        language = await resolver.resolve_language(patient_id)
        if language == DEFAULT_AI_LANGUAGE:
            return title, body
        translator = container.resolve(TranslationService)
        title_out = await translator.translate_cached(title, language)
        body_out = body_translation if body_translation else await translator.translate(body, language)
        return title_out, body_out
    except Exception as exc:
        logger.warning("notification localization failed for %s: %s", patient_id, exc)
        return title, body


async def _persist(patient_id, category, title, body, severity, deeplink, data):
    try:
        from lib.models.patient_notification import PatientNotification
        store = container.resolve(PostgresStore)
        notif = PatientNotification(
            patient_id=UUID(patient_id), category=category, title=title, body=body,
            severity=severity, deeplink=deeplink, data=data,
        )
        async with store.get_session() as session:
            session.add(notif)
            await session.commit()
            await session.refresh(notif)
        return notif.id
    except Exception as exc:
        logger.warning("notification persist failed for %s: %s", patient_id, exc)
        return None


async def _send_fcm(patient_id, title, body, channel_key, group_key, data, *, skip_permission_check):
    try:
        from lib.services.fcm_service import FCMService
        await FCMService().send_fcm_notification_to_user_devices(
            user_id=patient_id, title=title, body=body,
            channel_key=channel_key, group_key=group_key, data=data,
            skip_permission_check=skip_permission_check,
        )
        return True
    except Exception as exc:
        logger.warning("FCM send failed for %s (%s): %s", patient_id, channel_key, exc)
        return False
