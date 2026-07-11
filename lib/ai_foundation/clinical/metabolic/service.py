"""
Metabolic service — the interface agents call. Wraps the engine, assembler, outcome
tracking, and clinical audit into a clean async API.

Usage:
    service = MetabolicService(retriever=qdrant, postgres_store=postgres)
    contract = await service.assess(patient_id, meal_dict)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from lib.ai_foundation.retrieval.qdrant import QdrantRetriever
from lib.core.postgres_store import PostgresStore

from .assembler import DataAssembler
from .contracts import EngineContract
from .data_sufficiency import assess_readiness
from .engine import MetabolicEngine
from .enrichment import enrich
from .lenses import apply_lenses
from .nudge import build_nudges
from .outcome import OutcomeRepository, advice_event_from_contract
from .render import build_prompt
from .util import meal_slot as _meal_slot

logger = logging.getLogger(__name__)


class MetabolicService:
    """Injected into agents. Wraps the full metabolic clinical pipeline."""

    def __init__(
        self,
        *,
        retriever: QdrantRetriever,
        postgres_store: PostgresStore,
        clickhouse_store=None,
    ) -> None:
        self._engine = MetabolicEngine()
        self._assembler = DataAssembler(retriever=retriever, postgres_store=postgres_store)
        self._outcome = OutcomeRepository(postgres_store)
        self._clickhouse = clickhouse_store

    async def assess(
        self,
        patient_id: str,
        meal: dict[str, Any],
        patient_state: dict[str, Any] | None = None,
        live_pre: float | None = None,
        trace_id: str | None = None,
    ) -> EngineContract:
        """Full metabolic assessment: prediction + attribution + lever + safety + BMIQ.

        Returns a typed EngineContract. Also:
        - Logs clinical decision to audit trail
        - Processes pending follow-ups from prior advice (if CGM data available)
        - Logs new advice events on SUGGEST
        """
        if patient_state is None:
            patient_state = await self._assembler.build_patient_state(patient_id)

        contract = self._engine.assess(patient_state, meal)
        contract = enrich(contract, patient_state, meal, live_pre=live_pre)
        contract["lenses"] = apply_lenses(patient_state)

        # -- outcome loop: process follow-ups + log advice --
        await self._process_followups(patient_id)
        await self._log_advice_if_suggest(patient_id, contract, meal)

        # -- clinical decision audit (append-only, never fails the request) --
        try:
            await self._outcome.log_decision(patient_id, contract, trace_id=trace_id)
        except Exception:
            logger.warning("audit log failed for %s, continuing", patient_id, exc_info=True)

        return EngineContract.model_validate(contract)

    async def readiness(self, patient_id: str) -> dict[str, Any]:
        """Data sufficiency check: does this patient have enough data for personal numbers?"""
        patient_state = await self._assembler.build_patient_state(patient_id)
        signals = await self._assembler.build_signals(patient_id, patient_state)
        return assess_readiness(signals)

    async def risk_profile(self, patient_id: str) -> dict[str, Any]:
        """MMIQ risk tier + BMIQ body comp + drift flags (no meal needed)."""
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
            "lenses": apply_lenses(patient_state),
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

        contract = await self.assess(patient_id, meal, patient_state=patient_state)
        nudges = build_nudges(
            contract=contract.model_dump(),
            signals={"cold_start": readiness["meal_model"]["tier"] == "cold_start"},
        )
        prompt = build_prompt(contract.model_dump())

        return {
            "mode": "grounded",
            "contract": contract,
            "readiness": readiness,
            "nudges": nudges,
            "render_prompt": prompt,
        }

    async def outcome_rollup(self, valid_floor: int = 10) -> list[dict[str, Any]]:
        """Aggregate advice efficacy stats across all patients."""
        return await self._outcome.rollup(valid_floor=valid_floor)

    def build_meal_dict(self, meal_data: dict[str, Any], hour: int | None = None) -> dict[str, Any]:
        """Convenience: map a meal payload to engine input format."""
        return self._assembler.build_meal_dict(meal_data, hour)

    # Uncertainty band around the predicted rise, by engine confidence.
    # The band IS the uncertainty statement — a cold-start prediction must
    # not claim the same precision as one learned from 20+ paired meals.
    # An observed (already measured) response carries only sensor noise.
    _BAND_BY_CONFIDENCE: dict[str, int] = {"high": 8, "moderate": 12, "cold-start": 18}
    _BAND_OBSERVED = 5

    def to_glucose_prediction(
        self,
        contract: EngineContract | dict[str, Any],
        *,
        live_pre: float | None = None,
    ) -> dict[str, Any] | None:
        """Map engine contract to the production GlucosePrediction shape.

        Three-tier display policy (clinical rule: never present a number as
        measured when part of it is assumed):

        1. ``live_pre`` given (real CGM reading at meal time) → ABSOLUTE
           range anchored on it: "you're at 102 → expect ~103-115".
        2. No live reading → RISE range ("+3-15 above your current level").
           The twin prior is deliberately NOT used as an absolute anchor —
           it is an estimate, and presenting it as measured would mislead.
        3. Not enough data → the existing ``_show_number`` gate suppresses
           the number entirely (caller falls back).
        """
        c = contract.model_dump() if isinstance(contract, EngineContract) else contract
        pr = c.get("prediction") or {}
        rise = pr.get("observed_mgdl")
        kind = "observed"
        if rise is None:
            rise = pr.get("rise_mgdl")
            kind = "predicted"
        if rise is None:
            return None

        rise = float(rise)
        conf_raw = str(pr.get("confidence", "moderate")).lower()
        conf_map = {"high": "high", "moderate": "medium", "cold-start": "low"}
        conf = conf_map.get(conf_raw, "medium")
        band = (
            self._BAND_OBSERVED if kind == "observed"
            else self._BAND_BY_CONFIDENCE.get(conf_raw, 12)
        )

        rise_low = int(round(max(0.0, rise - band)))
        rise_high = int(round(rise + band))

        if live_pre is not None:
            basis = "absolute"
            range_low = int(round(live_pre + max(0.0, rise - band)))
            range_high = int(round(live_pre + rise + band))
            pre_meal = int(round(live_pre))
        else:
            basis = "rise"
            range_low, range_high = rise_low, rise_high
            pre_meal = None

        lever = c.get("lever") or {}
        rationale = c.get("fact", "")
        if lever.get("say") and lever.get("cite"):
            rationale += " One move: %s [%s]." % (lever["say"], lever["cite"])

        v31 = c.get("v31") or {}

        # The twin prior is exposed ONLY as a labeled estimate for
        # orientation — never merged into the range, never presented as
        # measured, and ONLY when it is a true time-of-day pattern
        # ("90d_prior"). The flat 90-day mean is NOT time-specific, so
        # surfacing it under "at this time" copy would mislabel it.
        prior = (v31.get("pre_prior") or {}) if isinstance(c.get("v31"), dict) else {}
        if prior.get("provenance") != "90d_prior":
            prior = {}

        # "Similar meals" must mean similar meals: the top-k same-slot,
        # carb-proximate past meals (evidence_meals) — NOT n_meals_learned,
        # which is the personal model's total training count.
        n_similar = len(v31.get("evidence_meals") or [])

        return {
            "range_mg_dl_low": range_low,
            "range_mg_dl_high": range_high,
            "basis": basis,
            "pre_meal_mg_dl": pre_meal,
            "pre_meal_estimate_mg_dl": (
                int(round(float(prior["value"])))
                if pre_meal is None and prior.get("value") is not None else None
            ),
            "pre_meal_estimate_source": (
                prior.get("provenance") if pre_meal is None and prior.get("value") is not None else None
            ),
            "rise_mg_dl_low": rise_low,
            "rise_mg_dl_high": rise_high,
            "peak_minutes_after": v31.get("peak_minutes", 60),
            "confidence": conf,
            "n_similar_meals": n_similar,
            "n_meals_learned": pr.get("n_meals_learned", 0),
            "evidence": [],
            "_evidence_meals": v31.get("evidence_meals") or [],
            "rationale": rationale.strip(),
            "_source": "metabolic_engine",
            "_kind": kind,
            "_output_mode": c.get("output_mode"),
            "_attribution": (c.get("attribution") or {}).get("label"),
            "_safety_unchecked": v31.get("safety_unchecked"),
            "_show_number": v31.get("show_number_to_patient", True),
            "_confidence_tier": v31.get("confidence_tier"),
            "_peak_basis": v31.get("peak_minutes_basis"),
        }

    # -- internal: outcome loop wiring --

    async def _log_advice_if_suggest(self, patient_id: str, contract: dict, meal: dict) -> None:
        """If the contract is a SUGGEST, log the advice event."""
        try:
            slot = _meal_slot(meal.get("hour"))
            event = advice_event_from_contract(
                contract, patient_id,
                track="glucose",
                trigger=f"{slot}_suggest",
                meal_slot=slot,
                meal_macros={k: meal.get(k) for k in ("carb", "protein", "fiber", "fat", "cal") if meal.get(k) is not None},
                meal_time=datetime.now(timezone.utc),
            )
            if event:
                await self._outcome.log_advice(event)
        except Exception:
            logger.warning("advice logging failed for %s, continuing", patient_id, exc_info=True)

    async def _process_followups(self, patient_id: str) -> None:
        """Check for pending advice events and follow up with CGM data if available."""
        if not self._clickhouse:
            return
        try:
            pending = await self._outcome.get_pending_followups(patient_id)
            for event in pending:
                await self._followup_with_cgm(event)
        except Exception:
            logger.warning("followup processing failed for %s, continuing", patient_id, exc_info=True)

    async def _followup_with_cgm(self, event) -> None:
        """Fetch CGM data around the advised meal and record the follow-up."""
        if not self._clickhouse or not event.meal_time:
            return
        try:
            from lib.services.reports.cgm.queries import generate_readings_around_meal_query
            query, params = generate_readings_around_meal_query(
                str(event.patient_id),
                event.meal_time.strftime("%Y-%m-%d %H:%M:%S"),
                before_minutes=15,
                after_minutes=120,
            )
            # clickhouse-driver is sync — run off the event loop
            results = await asyncio.to_thread(self._clickhouse.client.execute, query, params)
            if not results:
                return

            pre_readings = [r for r in results if r[0] < event.meal_time]
            post_readings = [r for r in results if r[0] >= event.meal_time]

            if not pre_readings or not post_readings:
                return

            cgm_pre = pre_readings[-1][1]    # last reading before meal
            cgm_peak = max(r[1] for r in post_readings)  # highest after meal
            observed_rise = cgm_peak - cgm_pre

            await self._outcome.record_followup(
                event.id,
                observed_delta=round(observed_rise, 1),
                cgm_pre=round(cgm_pre, 1),
                cgm_peak=round(cgm_peak, 1),
                evidence=f"CGM: pre={cgm_pre:.0f}, peak={cgm_peak:.0f}, rise={observed_rise:.0f}",
            )
        except Exception:
            logger.debug("CGM followup failed for event %s, will retry next assess", event.id, exc_info=True)
