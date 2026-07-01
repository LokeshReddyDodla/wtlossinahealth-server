"""
Metabolic service — the interface agents call. Wraps the engine, assembler, and data sufficiency
into a clean async API. Agents never touch the raw engine or data stores directly.

Usage:
    service = MetabolicService(retriever=qdrant, postgres_store=postgres)
    contract = await service.assess(patient_id, meal_dict)
    readiness = await service.readiness(patient_id)
"""

from __future__ import annotations

import logging
from typing import Any

from lib.ai_foundation.retrieval.qdrant import QdrantRetriever
from lib.core.postgres_store import PostgresStore

from .assembler import DataAssembler
from .data_sufficiency import assess_readiness
from .engine import MetabolicEngine
from .nudge import build_nudges
from .render import build_prompt

logger = logging.getLogger(__name__)


class MetabolicService:
    """Injected into agents like ModelGateway. Wraps the full metabolic clinical pipeline."""

    def __init__(
        self,
        *,
        retriever: QdrantRetriever,
        postgres_store: PostgresStore,
    ) -> None:
        self._engine = MetabolicEngine()
        self._assembler = DataAssembler(retriever=retriever, postgres_store=postgres_store)

    async def assess(
        self,
        patient_id: str,
        meal: dict[str, Any],
        patient_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Full metabolic assessment: prediction + attribution + lever + safety + BMIQ.

        If patient_state is provided, uses it directly (for callers that already fetched data).
        Otherwise fetches from stores via the assembler.
        """
        if patient_state is None:
            patient_state = await self._assembler.build_patient_state(patient_id)

        contract = self._engine.assess(patient_state, meal)
        return contract

    async def readiness(self, patient_id: str) -> dict[str, Any]:
        """Data sufficiency check: does this patient have enough data for personal numbers?"""
        patient_state = await self._assembler.build_patient_state(patient_id)
        signals = await self._assembler.build_signals(patient_id, patient_state)
        return assess_readiness(signals)

    async def risk_profile(self, patient_id: str) -> dict[str, Any]:
        """MMIQ risk tier + BMIQ body comp + drift flags (no meal needed).

        Runs the engine with a neutral meal to get patient-level signals only.
        """
        patient_state = await self._assembler.build_patient_state(patient_id)
        neutral_meal = {"carb": 0, "protein": 0, "fiber": 0, "cal": 0, "pre": 100, "hour": 12}
        contract = self._engine.assess(patient_state, neutral_meal)

        return {
            "mmiq_tier": (contract.get("phenotype") or {}).get("tier"),
            "mmiq_driver": (contract.get("attribution") or {}).get("cgm_driver"),
            "bmiq": contract.get("bmiq"),
            "weight_trend": contract.get("weight_trend"),
            "patient_flags": contract.get("patient_flags"),
            "safety_flags": contract.get("safety_flags"),
        }

    async def assess_with_context(
        self,
        patient_id: str,
        meal: dict[str, Any],
    ) -> dict[str, Any]:
        """Full assessment + readiness + nudges + render prompt — everything a coach turn needs."""
        patient_state = await self._assembler.build_patient_state(patient_id)
        signals = await self._assembler.build_signals(patient_id, patient_state)
        readiness = assess_readiness(signals)

        if readiness["overall_output_mode"] == "EDUCATIONAL":
            return {
                "mode": "general_fallback",
                "contract": None,
                "readiness": readiness,
                "nudges": readiness.get("nudge_to_share", []),
                "render_prompt": None,
            }

        contract = self._engine.assess(patient_state, meal)
        nudges = build_nudges(contract=contract, signals={"cold_start": readiness["meal_model"]["tier"] == "cold_start"})
        prompt = build_prompt(contract)

        return {
            "mode": "grounded",
            "contract": contract,
            "readiness": readiness,
            "nudges": nudges,
            "render_prompt": prompt,
        }

    def build_meal_dict(self, meal_data: dict[str, Any], hour: int | None = None) -> dict[str, Any]:
        """Convenience: map a meal payload to engine input format."""
        return self._assembler.build_meal_dict(meal_data, hour)

    def to_glucose_prediction(self, contract: dict[str, Any], band_mgdl: int = 12) -> dict[str, Any] | None:
        """Map engine contract to the production GlucosePrediction shape (for MealAnalysisAgent compatibility)."""
        pr = contract.get("prediction") or {}
        rise = pr.get("observed_mgdl")
        kind = "observed"
        if rise is None:
            rise = pr.get("rise_mgdl")
            kind = "predicted"
        if rise is None:
            return None

        rise = float(rise)
        conf_map = {"high": "high", "moderate": "medium", "cold-start": "low"}
        conf = conf_map.get(str(pr.get("confidence", "moderate")).lower(), "medium")

        lever = contract.get("lever") or {}
        rationale = contract.get("fact", "")
        if lever.get("say") and lever.get("cite"):
            rationale += " One move: %s [%s]." % (lever["say"], lever["cite"])

        return {
            "range_mg_dl_low": int(round(max(0.0, rise - band_mgdl))),
            "range_mg_dl_high": int(round(rise + band_mgdl)),
            "peak_minutes_after": 60,
            "confidence": conf,
            "n_similar_meals": pr.get("n_meals_learned", 0),
            "evidence": [],
            "rationale": rationale.strip(),
            "_source": "metabolic_engine",
            "_kind": kind,
            "_output_mode": contract.get("output_mode"),
            "_attribution": (contract.get("attribution") or {}).get("label"),
        }
