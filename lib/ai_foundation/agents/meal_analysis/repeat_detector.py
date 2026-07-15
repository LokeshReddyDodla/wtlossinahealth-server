"""
Repeat detector.

Deterministic flags based on the patient's recent meal history:
- already logged this slot today (collision)
- same as previous meal (one-tap repeat candidate)
- how many times the patient has had this meal in the last 7 days

No LLM. No DB access — operates on MealAnalysisContext already loaded.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .context_loader import MealAnalysisContext
from .contracts import (
    MealExtraction,
    MealSlot,
    PatientMealRef,
    RepeatFlag,
    RepeatSuggestion,
)


SIMILARITY_THRESHOLD = 0.6


def detect_repeat(
    *,
    extraction: MealExtraction,
    context: MealAnalysisContext,
    slot: MealSlot,
) -> RepeatFlag:
    """Produce a RepeatFlag based on extraction vs context.today/recent."""
    today_for_slot = (context.today_meals_by_slot or {}).get(slot, [])
    slot_collision: PatientMealRef | None = _pick_slot_collision(
        extraction=extraction,
        today_for_slot=today_for_slot,
        recent_meals=context.recent_meals,
        slot=slot,
    )

    prev = _most_recent(context.recent_meals)
    same_as_prev: PatientMealRef | None = None
    if prev is not None and _names_match(extraction, prev):
        same_as_prev = _to_ref(prev)

    if (
        same_as_prev is not None
        and slot_collision is not None
        and same_as_prev.meal_id == slot_collision.meal_id
    ):
        same_as_prev = None

    count_7d = _count_in_last_days(
        extraction=extraction,
        recent_meals=context.recent_meals,
        now=context.local_now,
        days=7,
    )

    suggestion = _suggest(
        slot_collision=slot_collision is not None,
        same_as_prev=same_as_prev is not None,
        count_7d=count_7d,
    )

    return RepeatFlag(
        already_logged_this_slot_today=slot_collision is not None,
        same_slot_meal_today=slot_collision,
        same_as_previous_meal=same_as_prev,
        same_meal_count_last_7d=count_7d,
        suggestion=suggestion,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pick_slot_collision(
    *,
    extraction: MealExtraction,
    today_for_slot: list[PatientMealRef],
    recent_meals: list[dict[str, Any]],
    slot: MealSlot,
) -> PatientMealRef | None:
    """Select the meal (if any) that counts as "already logged this slot".

    For BREAKFAST / LUNCH / DINNER: any existing meal in the slot collides —
    the app assumes one entry per main-meal slot per day.

    For SNACK: only collide when the food matches an existing snack — users
    legitimately log several distinct snacks per day. Matching prefers
    item-overlap via `recent_meals` (has full items) and falls back to
    name-only match for snacks that Qdrant hasn't indexed yet.
    """
    if not today_for_slot:
        return None
    if slot != MealSlot.SNACK:
        return today_for_slot[0]

    recent_by_id = {
        str(m.get("meal_id")): m for m in recent_meals if m.get("meal_id")
    }
    for ref in today_for_slot:
        prior = recent_by_id.get(str(ref.meal_id))
        if prior is not None:
            if _names_match(extraction, prior):
                return ref
            continue
        ext_name = (extraction.name or "").strip().lower()
        ref_name = (ref.meal_name or "").strip().lower()
        if ext_name and ref_name and ext_name == ref_name:
            return ref
    return None


def _most_recent(recent: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not recent:
        return None
    return recent[0]  # context_loader sorts date desc, time desc


def _names_match(extraction: MealExtraction, prev: dict[str, Any]) -> bool:
    name_a = (extraction.name or "").strip().lower()
    name_b = (prev.get("name") or "").strip().lower()
    if name_a and name_b and name_a == name_b:
        return True
    return _item_overlap(extraction, prev) >= SIMILARITY_THRESHOLD


def _item_overlap(extraction: MealExtraction, prev: dict[str, Any]) -> float:
    """Jaccard-ish: shared item names / union item names."""
    a = {it.name.strip().lower() for it in extraction.items}
    b = {
        (it.get("name") or "").strip().lower()
        for it in (prev.get("items") or [])
    }
    a.discard("")
    b.discard("")
    if not a or not b:
        return 0.0
    union = a | b
    return len(a & b) / len(union)


def _count_in_last_days(
    *,
    extraction: MealExtraction,
    recent_meals: list[dict[str, Any]],
    now: datetime,
    days: int,
) -> int:
    if not recent_meals:
        return 0
    cutoff = now - timedelta(days=days)
    count = 0
    for meal in recent_meals:
        consumed_at_str = meal.get("consumed_at")
        if not consumed_at_str:
            continue
        try:
            consumed_at = datetime.fromisoformat(consumed_at_str)
        except ValueError:
            continue
        if consumed_at.tzinfo is None and now.tzinfo is not None:
            consumed_at = consumed_at.replace(tzinfo=now.tzinfo)
        if consumed_at < cutoff:
            continue
        if _names_match(extraction, meal):
            count += 1
    return count


def _suggest(
    *, slot_collision: bool, same_as_prev: bool, count_7d: int
) -> RepeatSuggestion:
    if slot_collision:
        return RepeatSuggestion.ASK_CONFIRM
    if same_as_prev and count_7d >= 3:
        return RepeatSuggestion.LOG_AGAIN
    return RepeatSuggestion.NONE


def _to_ref(meal: dict[str, Any]) -> PatientMealRef | None:
    return PatientMealRef.from_payload(meal)
