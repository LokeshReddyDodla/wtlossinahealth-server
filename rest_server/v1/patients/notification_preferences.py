"""Patient notification preferences — per-category mute.

The patient sees every mutable category with its on/off state and can toggle
it. CRITICAL categories (meds, safety) are never listed — they're unmutable
by policy, so the API refuses to disable them.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from lib.core.constants import ProfileTypeEnum
from lib.core.container import container
from lib.core.postgres_store import PostgresStore
from lib.dependencies.actor import Actor, get_current_actor
from lib.models.patient_notification_preference import PatientNotificationPreference
from lib.services.notifications.policy import _CATEGORY_TIER, policy_for
from rest_server.response_models import SuccessResponse

from .router import router

logger = logging.getLogger(__name__)

# Only categories the broker actually honors a mute for — CRITICAL (unmutable)
# and EVENT (the patient acted, so they get the reply) are excluded, so the
# API never offers a toggle that does nothing.
_MUTABLE_CATEGORIES = sorted(c for c in _CATEGORY_TIER if policy_for(c).mutable)

_LABELS = {
    "meal_logged": "Meal feedback",
    "smbg_logged": "Glucose reading feedback",
    "symptom_logged": "Symptom check-ins",
    "cgm_threshold_crossed": "Glucose alerts",
    "proactive_insight": "Health insights",
    "daily_brief": "Daily brief",
    "care_intent_nudge": "Care-team reminders",
    "re_engagement": "Check-in nudges",
    "gamification": "Rewards & streaks",
    "streak_reminder": "Streak reminders",
}


class PreferenceItem(BaseModel):
    category: str
    label: str
    enabled: bool


class PreferenceUpdate(BaseModel):
    category: str
    enabled: bool = Field(description="false = mute this category")


@router.get("/notification-preferences", response_model=SuccessResponse[list[PreferenceItem]])
async def get_notification_preferences(
    current_actor: Annotated[Actor, Depends(get_current_actor(
        allowed_roles=[ProfileTypeEnum.PATIENT], check_permissions=False,
    ))],
):
    """Every mutable category + its current on/off (default on)."""
    pid = current_actor.model.patient_id
    store = container.resolve(PostgresStore)
    async with store.get_session() as session:
        rows = (await session.scalars(
            select(PatientNotificationPreference).where(
                PatientNotificationPreference.patient_id == pid
            )
        )).all()
    muted = {r.category for r in rows if not r.enabled}
    items = [
        PreferenceItem(category=c, label=_LABELS.get(c, c), enabled=c not in muted)
        for c in _MUTABLE_CATEGORIES
    ]
    return SuccessResponse(message="OK", data=items)


@router.patch("/notification-preferences", response_model=SuccessResponse[PreferenceItem])
async def update_notification_preference(
    payload: PreferenceUpdate,
    current_actor: Annotated[Actor, Depends(get_current_actor(
        allowed_roles=[ProfileTypeEnum.PATIENT], check_permissions=False,
    ))],
):
    """Toggle one category. Refuses to mute an unmutable CRITICAL category."""
    if payload.category not in _MUTABLE_CATEGORIES:
        raise HTTPException(
            status_code=422,
            detail=f"'{payload.category}' can't be muted — it's a critical safety notification.",
        )
    pid = current_actor.model.patient_id
    store = container.resolve(PostgresStore)
    async with store.get_session() as session:
        stmt = pg_insert(PatientNotificationPreference).values(
            patient_id=pid, category=payload.category, enabled=payload.enabled,
        ).on_conflict_do_update(
            constraint="uq_patient_notif_pref",
            set_={"enabled": payload.enabled},
        )
        await session.execute(stmt)
        await session.commit()
    return SuccessResponse(
        message="Updated",
        data=PreferenceItem(
            category=payload.category,
            label=_LABELS.get(payload.category, payload.category),
            enabled=payload.enabled,
        ),
    )
