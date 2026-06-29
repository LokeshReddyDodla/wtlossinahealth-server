"""
Data assembler — fetches patient data from Qdrant/Postgres and maps it into
the engine's input format (patient_state dict + signals dict).

The engine is pure stdlib and knows nothing about Qdrant, Postgres, or async.
This module bridges that gap.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from lib.ai_foundation.retrieval.base import RetrievalRequest
from lib.ai_foundation.retrieval.qdrant import QdrantRetriever
from lib.core.postgres_store import PostgresStore

logger = logging.getLogger(__name__)

_CGM_SUMMARY_TYPE = "cgm_summary_stats"
_CGM_RANGE_TYPE = "cgm_range_stats"
_MEAL_TYPE = "meal"
_PROFILE_TYPE = "profile"
_MEDICATION_TYPE = "medication"


class DataAssembler:
    """Fetches patient data from stores and builds the dicts the MetabolicEngine expects."""

    def __init__(
        self,
        *,
        retriever: QdrantRetriever,
        postgres_store: PostgresStore,
    ) -> None:
        self._qdrant = retriever
        self._postgres = postgres_store

    async def build_patient_state(
        self,
        patient_id: str,
        history_days: int = 90,
    ) -> dict[str, Any]:
        profile, meals, cgm_summary, medications = await asyncio.gather(
            self._load_profile(patient_id),
            self._load_meal_history(patient_id, history_days),
            self._load_cgm_summary(patient_id),
            self._load_medications(patient_id),
            return_exceptions=True,
        )

        profile = _safe(profile, {})
        meals = _safe(meals, [])
        cgm_summary = _safe(cgm_summary, {})
        medications = _safe(medications, [])

        if medications:
            profile.setdefault("meds", [m.get("name", "") for m in medications])

        history = _meals_to_engine_history(meals)

        return {
            "history": history,
            "cgm_summary": cgm_summary or None,
            "profile": profile,
            "base": _extract_base(cgm_summary),
        }

    async def build_signals(self, patient_id: str, patient_state: dict | None = None) -> dict[str, Any]:
        state = patient_state or await self.build_patient_state(patient_id)
        history = state.get("history") or []
        cgm = state.get("cgm_summary") or {}

        cgm_days = cgm.get("days_of_data", 0) or 0

        return {
            "paired_meals": len(history),
            "quantities": {
                "cgm": cgm_days,
                "food_photos": len(history),
            },
            "cohort_n": None,
        }

    def build_meal_dict(self, meal_data: dict[str, Any], hour: int | None = None) -> dict[str, Any]:
        """Map a meal payload (from Qdrant or MealExtraction) to the engine's meal input format."""
        macros = meal_data.get("macros") or meal_data.get("nutrition") or meal_data
        return {
            "carb": _num(macros.get("carbohydrates") or macros.get("carbs") or macros.get("carb")),
            "protein": _num(macros.get("proteins") or macros.get("protein")),
            "fiber": _num(macros.get("fiber")),
            "fat": _num(macros.get("fats") or macros.get("fat")),
            "cal": _num(macros.get("calories") or macros.get("cal")),
            "pre": _num(meal_data.get("pre_meal_glucose") or meal_data.get("pre")),
            "hour": hour,
        }

    # -- Qdrant loaders --

    async def _load_profile(self, patient_id: str) -> dict[str, Any]:
        try:
            results = await self._qdrant.retrieve_filtered(
                RetrievalRequest(
                    query="",
                    patient_ids=[patient_id],
                    data_types=[_PROFILE_TYPE],
                    limit=1,
                )
            )
            for r in results:
                return r.payload or {}
            return {}
        except Exception as exc:
            logger.warning("assembler: load_profile failed for %s: %s", patient_id, exc)
            return {}

    async def _load_meal_history(self, patient_id: str, days: int) -> list[dict[str, Any]]:
        try:
            start = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
            end = datetime.utcnow().date().isoformat()
            results = await self._qdrant.retrieve_filtered(
                RetrievalRequest(
                    query="",
                    patient_ids=[patient_id],
                    data_types=[_MEAL_TYPE],
                    date_start=start,
                    date_end=end,
                    limit=500,
                )
            )
            return [r.payload for r in results if (r.data_type or r.payload.get("data_type")) == _MEAL_TYPE]
        except Exception as exc:
            logger.warning("assembler: load_meals failed for %s: %s", patient_id, exc)
            return []

    async def _load_cgm_summary(self, patient_id: str) -> dict[str, Any]:
        try:
            results = await self._qdrant.retrieve_filtered(
                RetrievalRequest(
                    query="",
                    patient_ids=[patient_id],
                    data_types=[_CGM_SUMMARY_TYPE],
                    limit=5,
                )
            )
            # ponytail: take the most recent summary
            for r in sorted(results, key=lambda r: r.payload.get("start_time", 0), reverse=True):
                if (r.data_type or r.payload.get("data_type")) == _CGM_SUMMARY_TYPE:
                    return _cgm_payload_to_engine(r.payload)
            return {}
        except Exception as exc:
            logger.warning("assembler: load_cgm_summary failed for %s: %s", patient_id, exc)
            return {}

    async def _load_medications(self, patient_id: str) -> list[dict[str, Any]]:
        try:
            results = await self._qdrant.retrieve_filtered(
                RetrievalRequest(
                    query="",
                    patient_ids=[patient_id],
                    data_types=[_MEDICATION_TYPE],
                    limit=10,
                )
            )
            return [
                {"name": r.payload.get("medication_name") or r.payload.get("name", "")}
                for r in results
                if (r.data_type or r.payload.get("data_type")) == _MEDICATION_TYPE
            ]
        except Exception as exc:
            logger.debug("assembler: load_medications failed for %s: %s", patient_id, exc)
            return []


# -- Helpers --

def _safe(value: Any, default: Any) -> Any:
    return default if isinstance(value, BaseException) else value


def _num(x: Any) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
        return v if v == v else None  # NaN check
    except (ValueError, TypeError):
        return None


def _meals_to_engine_history(meals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map Qdrant meal payloads to engine history format."""
    history = []
    for m in meals:
        n = m.get("nutrition") or {}
        carb = _num(n.get("carbohydrates") or n.get("carbs"))
        if carb is None:
            continue

        # peak rise from linked CGM spike (if available)
        peak = _num(m.get("glucose_rise") or m.get("peak_rise") or m.get("glucose_peak_rise"))

        meal_time = m.get("meal_time") or m.get("time")
        hour = None
        if meal_time:
            try:
                if isinstance(meal_time, str) and ":" in meal_time:
                    hour = int(meal_time.split(":")[0])
                elif isinstance(meal_time, (int, float)):
                    hour = int(meal_time)
            except (ValueError, TypeError):
                pass

        history.append({
            "carb": carb,
            "protein": _num(n.get("proteins") or n.get("protein")),
            "fiber": _num(n.get("fiber")),
            "cal": _num(n.get("calories")),
            "pre": _num(m.get("pre_meal_glucose")),
            "hour": hour,
            "peak": peak,
        })
    return history


def _cgm_payload_to_engine(payload: dict[str, Any]) -> dict[str, Any]:
    """Map Qdrant CGM summary payload to engine cgm_summary format."""
    return {
        "tir": _num(payload.get("time_in_range") or payload.get("tir")),
        "cv": _num(payload.get("cv") or payload.get("coefficient_of_variation")),
        "mean": _num(payload.get("mean_glucose") or payload.get("mean") or payload.get("average_glucose")),
        "postprandial_share": _num(payload.get("postprandial_share")),
        "nocturnal_share": _num(payload.get("nocturnal_share")),
        "days_of_data": _num(payload.get("days_of_data") or payload.get("total_days")),
    }


def _extract_base(cgm: dict[str, Any]) -> dict[str, Any]:
    """Extract base/recent-state signals from CGM summary for the engine."""
    if not cgm:
        return {}
    return {
        "recent_cv": _num(cgm.get("cv")),
        "overnight_mean": _num(cgm.get("mean")),
    }
