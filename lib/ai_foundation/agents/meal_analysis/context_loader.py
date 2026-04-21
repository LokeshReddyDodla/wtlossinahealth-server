"""
MealAnalysisContext loader.

Reads patient health data (profile, meals, diet plan, CGM events,
medications, workouts) from Qdrant and conversational memory from
MongoDB. Parallel fetch via asyncio.gather.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date as date_cls
from datetime import datetime, timedelta
from typing import Any

from lib.ai_foundation.config import settings
from lib.ai_foundation.memory.base import MemoryFact
from lib.ai_foundation.memory.mongo_store import MongoMemoryStore
from lib.ai_foundation.retrieval.base import RetrievalRequest, RetrievalResult
from lib.ai_foundation.retrieval.qdrant import QdrantRetriever

from .contracts import MealSlot, PatientMealRef

logger = logging.getLogger(__name__)

MEAL_DATA_TYPE = "meal"
CGM_EVENT_TYPES = [
    "hyper_event",
    "hypo_event",
    "rapid_spike_event",
    "rapid_drop_event",
]
MEDICATION_DATA_TYPE = "medication"
WORKOUT_DATA_TYPE = "patient_workout"
DIET_PLAN_DATA_TYPE = "diet_plan"
PROFILE_DATA_TYPE = "profile"


@dataclass
class MealAnalysisContext:
    """Everything the pipeline needs that doesn't depend on extraction."""

    patient_id: str
    local_now: datetime
    profile: dict[str, Any] = field(default_factory=dict)
    recent_meals: list[dict[str, Any]] = field(default_factory=list)
    today_meals_by_slot: dict[MealSlot, list[PatientMealRef]] = field(
        default_factory=dict
    )
    active_diet_plan: dict[str, Any] | None = None
    memories: list[MemoryFact] = field(default_factory=list)
    has_cgm: bool = False
    cgm_events: list[dict[str, Any]] = field(default_factory=list)
    medications: list[dict[str, Any]] = field(default_factory=list)
    recent_workouts: list[dict[str, Any]] = field(default_factory=list)


class MealContextLoader:
    """Parallel loader for MealAnalysisContext."""

    def __init__(
        self,
        *,
        qdrant_retriever: QdrantRetriever,
        memory_store: MongoMemoryStore,
    ) -> None:
        self._qdrant = qdrant_retriever
        self._memory = memory_store

    async def load(
        self,
        *,
        patient_id: str,
        local_now: datetime,
        history_days: int | None = None,
    ) -> MealAnalysisContext:
        today = local_now.date()
        history_start = today - timedelta(
            days=history_days or settings.MEAL_HISTORY_DAYS
        )
        cgm_start = today - timedelta(days=settings.MEAL_CGM_EVENT_DAYS)
        workout_start = local_now - timedelta(
            hours=settings.MEAL_WORKOUT_LOOKBACK_HOURS
        )

        (
            profile,
            meals,
            active_plan,
            memories,
            cgm_events,
            medications,
            recent_workouts,
        ) = await asyncio.gather(
            self._load_profile(patient_id),
            self._load_meals(patient_id, history_start, today),
            self._load_active_diet_plan(patient_id, today),
            self._memory.get_patient_facts(patient_id),
            self._load_cgm_events(patient_id, cgm_start, today),
            self._load_medications(patient_id),
            self._load_recent_workouts(patient_id, workout_start, local_now),
            return_exceptions=True,
        )

        meals = _unwrap(meals, [])
        recent_meals, today_by_slot = _partition_meals_by_date(meals, today)

        return MealAnalysisContext(
            patient_id=patient_id,
            local_now=local_now,
            profile=_unwrap(profile, {}),
            recent_meals=recent_meals,
            today_meals_by_slot=today_by_slot,
            active_diet_plan=_unwrap(active_plan, None),
            memories=_unwrap(memories, []),
            cgm_events=_unwrap(cgm_events, []),
            medications=_unwrap(medications, []),
            recent_workouts=_unwrap(recent_workouts, []),
            has_cgm=_derive_has_cgm(_unwrap(cgm_events, []), local_now),
        )

    # ── Qdrant loaders ───────────────────────────────────────────────────

    async def _load_profile(self, patient_id: str) -> dict[str, Any]:
        try:
            results = await self._qdrant.retrieve_filtered(
                RetrievalRequest(
                    query="",
                    patient_ids=[patient_id],
                    data_types=[PROFILE_DATA_TYPE],
                    limit=1,
                )
            )
            for r in results:
                dt = r.data_type or r.payload.get("data_type")
                if dt == PROFILE_DATA_TYPE:
                    return _profile_payload_to_dict(r.payload)
            return {}
        except Exception as exc:
            logger.warning("load_profile failed for %s: %s", patient_id, exc)
            return {}

    async def _load_meals(
        self, patient_id: str, start: date_cls, end: date_cls
    ) -> list[dict[str, Any]]:
        """All meals in [start, end] — caller splits into recent vs today."""
        try:
            results = await self._qdrant.retrieve_filtered(
                RetrievalRequest(
                    query="",
                    patient_ids=[patient_id],
                    data_types=[MEAL_DATA_TYPE],
                    date_start=start.isoformat(),
                    date_end=end.isoformat(),
                    limit=settings.MEAL_HISTORY_LIMIT,
                )
            )
            return [_meal_payload_to_dict(r) for r in results if _is_meal(r)]
        except Exception as exc:
            logger.warning("load_meals failed for %s: %s", patient_id, exc)
            return []

    async def _load_active_diet_plan(
        self, patient_id: str, today: date_cls
    ) -> dict[str, Any] | None:
        """Active diet plan payload with full `content` JSONB."""
        try:
            results = await self._qdrant.retrieve_filtered(
                RetrievalRequest(
                    query="",
                    patient_ids=[patient_id],
                    data_types=[DIET_PLAN_DATA_TYPE],
                    limit=5,
                )
            )
            active = [
                r.payload
                for r in results
                if (r.data_type or r.payload.get("data_type"))
                == DIET_PLAN_DATA_TYPE
                and (r.payload.get("plan_status") or "").upper() == "ACTIVE"
            ]
            if not active:
                return None
            # Pick the most recent by start_time if multiple active
            active.sort(key=lambda p: p.get("start_time") or 0, reverse=True)
            return active[0]
        except Exception as exc:
            logger.warning("load_diet_plan failed for %s: %s", patient_id, exc)
            return None

    async def _load_cgm_events(
        self, patient_id: str, start: date_cls, end: date_cls
    ) -> list[dict[str, Any]]:
        try:
            results = await self._qdrant.retrieve_filtered(
                RetrievalRequest(
                    query="",
                    patient_ids=[patient_id],
                    data_types=list(CGM_EVENT_TYPES),
                    date_start=start.isoformat(),
                    date_end=end.isoformat(),
                    limit=settings.MEAL_CGM_EVENT_LIMIT,
                )
            )
            event_types = set(CGM_EVENT_TYPES)
            return [
                _cgm_event_payload(r)
                for r in results
                if (r.data_type or r.payload.get("data_type")) in event_types
            ]
        except Exception as exc:
            logger.warning(
                "load_cgm_events failed for %s: %s", patient_id, exc
            )
            return []

    async def _load_medications(self, patient_id: str) -> list[dict[str, Any]]:
        try:
            results = await self._qdrant.retrieve_filtered(
                RetrievalRequest(
                    query="",
                    patient_ids=[patient_id],
                    data_types=[MEDICATION_DATA_TYPE],
                    limit=10,
                )
            )
            return [
                {
                    "name": r.payload.get("medication_name")
                    or r.payload.get("name"),
                    "text_repr": r.payload.get("text_repr", ""),
                    "payload": r.payload,
                }
                for r in results
                if (r.data_type or r.payload.get("data_type"))
                == MEDICATION_DATA_TYPE
            ]
        except Exception as exc:
            logger.debug(
                "load_medications failed for %s: %s", patient_id, exc
            )
            return []

    async def _load_recent_workouts(
        self, patient_id: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        try:
            results = await self._qdrant.retrieve_filtered(
                RetrievalRequest(
                    query="",
                    patient_ids=[patient_id],
                    data_types=[WORKOUT_DATA_TYPE],
                    date_start=start.date().isoformat(),
                    date_end=end.date().isoformat(),
                    limit=5,
                )
            )
            return [
                {
                    "workout_name": r.payload.get("workout_name")
                    or r.payload.get("name"),
                    "start_time": r.payload.get("start_time"),
                    "text_repr": r.payload.get("text_repr", ""),
                }
                for r in results
                if (r.data_type or r.payload.get("data_type"))
                == WORKOUT_DATA_TYPE
            ]
        except Exception as exc:
            logger.debug(
                "load_recent_workouts failed for %s: %s", patient_id, exc
            )
            return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unwrap(value: Any, default: Any) -> Any:
    if isinstance(value, BaseException):
        return default
    return value


def _coerce_slot(raw: str | None) -> MealSlot | None:
    if not raw:
        return None
    key = raw.strip().lower()
    try:
        return MealSlot(key)
    except ValueError:
        return None


def _is_meal(r: RetrievalResult) -> bool:
    dt = r.data_type or r.payload.get("data_type")
    return dt == MEAL_DATA_TYPE


def _partition_meals_by_date(
    meals: list[dict[str, Any]], today: date_cls
) -> tuple[list[dict[str, Any]], dict[MealSlot, list[PatientMealRef]]]:
    """Split meals: recent=everything, today_by_slot=grouped for today only."""
    today_iso = today.isoformat()
    today_by_slot: dict[MealSlot, list[PatientMealRef]] = {}

    for meal in meals:
        if meal.get("date") != today_iso:
            continue
        slot = _coerce_slot(meal.get("slot"))
        if slot is None:
            continue
        ref = _patient_meal_ref_from_dict(meal, slot)
        if ref is None:
            continue
        today_by_slot.setdefault(slot, []).append(ref)

    return meals, today_by_slot


def _patient_meal_ref_from_dict(
    meal: dict[str, Any], slot: MealSlot
) -> PatientMealRef | None:
    from uuid import UUID

    meal_id = meal.get("meal_id")
    if not meal_id:
        return None
    try:
        mid = UUID(str(meal_id))
    except (ValueError, TypeError):
        return None

    consumed_at_str = meal.get("consumed_at")
    try:
        consumed_at = (
            datetime.fromisoformat(consumed_at_str)
            if consumed_at_str
            else datetime.utcnow()
        )
    except ValueError:
        consumed_at = datetime.utcnow()

    return PatientMealRef(
        meal_id=mid,
        meal_name=meal.get("name") or "",
        consumed_at=consumed_at,
        slot=slot,
    )


def _meal_payload_to_dict(r: RetrievalResult) -> dict[str, Any]:
    p = r.payload or {}
    meal_date = p.get("meal_date")
    meal_time = p.get("meal_time")
    consumed_at = None
    if meal_date and meal_time:
        consumed_at = f"{meal_date}T{meal_time}"

    nutrition = p.get("nutrition") or {}
    return {
        "meal_id": p.get("meal_id"),
        "name": p.get("meal_name"),
        "slot": p.get("meal_type"),
        "date": meal_date,
        "time": meal_time,
        "consumed_at": consumed_at,
        "tags": p.get("tags") or [],
        "description": p.get("description"),
        "image_url": p.get("image_url"),
        "macros": {
            "calories": nutrition.get("calories"),
            "proteins": nutrition.get("proteins"),
            "carbohydrates": nutrition.get("carbohydrates"),
            "simple_carbs": nutrition.get("simple_carbs"),
            "complex_carbs": nutrition.get("complex_carbs"),
            "fats": nutrition.get("fats"),
            "fiber": nutrition.get("fiber"),
        },
        "micros": {
            "calcium": nutrition.get("calcium"),
            "iron": nutrition.get("iron"),
            "zinc": nutrition.get("zinc"),
            "magnesium": nutrition.get("magnesium"),
        },
        "items": [
            {
                "name": it.get("item_name"),
                "serving_quantity": it.get("serving_quantity"),
                "serving_unit": it.get("serving_unit"),
                "serving_size": it.get("serving_size"),
            }
            for it in (p.get("items") or [])
        ],
    }


def _cgm_event_payload(r: RetrievalResult) -> dict[str, Any]:
    p = r.payload or {}
    return {
        "data_type": r.data_type or p.get("data_type"),
        "start_time": p.get("start_time"),
        "end_time": p.get("end_time"),
        "peak_value": p.get("peak_value") or p.get("max_value"),
        "min_value": p.get("min_value"),
        "duration_minutes": p.get("duration_minutes"),
        "text_repr": p.get("text_repr", ""),
    }


def _profile_payload_to_dict(payload: dict[str, Any]) -> dict[str, Any]:
    """Select the fields our prompts actually use."""
    keys = (
        "age",
        "gender",
        "height",
        "weight",
        "bmi",
        "locale",
        "timezone",
        "type_of_diabetes",
        "years_with_diabetes",
        "average_sleep_duration",
    )
    return {k: payload[k] for k in keys if payload.get(k) is not None}


def _derive_has_cgm(cgm_events: list[dict[str, Any]], now: datetime) -> bool:
    """Patient has CGM if any event was recorded in the last 7 days."""
    cutoff_ms = int((now - timedelta(days=7)).timestamp() * 1000)
    for e in cgm_events:
        st = e.get("start_time")
        if isinstance(st, (int, float)) and st >= cutoff_ms:
            return True
    return False
