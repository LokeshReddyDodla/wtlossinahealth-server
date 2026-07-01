"""
MealAnalysisAgent — orchestrates the preview pipeline.

    1. load context in parallel
    2. extract (or resolve repeat_of_meal_id → prior extraction, or use items[])
    3. score (deterministic GL + LLM concerns/positives)
    4. parallel: alternatives, glucose prediction, plan check, repeat detection
    5. assemble MealAnalysisResult
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from lib.ai_foundation.agents.base import BaseAgent
from lib.ai_foundation.agents.state import AgentInput, AgentOutput
from lib.ai_foundation.events.bus import EventBus
from lib.ai_foundation.memory.base import MemoryStore
from lib.ai_foundation.models.gateway import ModelGateway
from lib.ai_foundation.prompts.registry import PromptRegistry
from lib.ai_foundation.retrieval.base import RetrievalRequest
from lib.ai_foundation.retrieval.qdrant import QdrantRetriever

from .alternatives import AlternativesEngine
from .context_loader import MealContextLoader
from .contracts import (
    ConfidenceLevel,
    ExtractedFoodItem,
    GlucosePrediction,
    MacroSet,
    MealAnalysisResult,
    MealExtraction,
    MealInsightsRequest,
    MealPreviewRequest,
    MealQuickResult,
)
from .extractor import MealExtractor
from .glucose_predictor import GlucosePredictor
from .plan_checker import check_plan
from lib.ai_foundation.clinical.metabolic.service import MetabolicService
from .repeat_detector import detect_repeat
from .scorer import MealScorer, estimate_glycemic_load

logger = logging.getLogger(__name__)


async def _maybe_await(result: Any) -> None:
    if inspect.isawaitable(result):
        await result


async def _timed(coro: Any) -> tuple[Any, int]:
    """Await ``coro`` and return ``(result, elapsed_ms)``."""
    t0 = time.perf_counter()
    result = await coro
    return result, int((time.perf_counter() - t0) * 1000)


class MealAnalysisAgent(BaseAgent):
    """Preview-only meal analysis pipeline.

    `analyze()` is the primary typed API. `run()` satisfies the BaseAgent
    interface by unpacking AgentInput.metadata into a MealPreviewRequest.
    """

    name = "meal_analysis"

    def __init__(
        self,
        *,
        gateway: ModelGateway,
        qdrant_retriever: QdrantRetriever,
        context_loader: MealContextLoader,
        extractor: MealExtractor,
        scorer: MealScorer,
        alternatives: AlternativesEngine,
        glucose_predictor: GlucosePredictor,
        metabolic_service: MetabolicService | None = None,
        memory: MemoryStore | None = None,
        prompts: PromptRegistry | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        super().__init__(
            gateway=gateway,
            memory=memory,
            prompts=prompts,
            event_bus=event_bus,
        )
        self._qdrant = qdrant_retriever
        self._ctx = context_loader
        self._extractor = extractor
        self._scorer = scorer
        self._alternatives = alternatives
        self._glucose = glucose_predictor
        self._metabolic = metabolic_service

    async def analyze(
        self,
        *,
        patient_id: str,
        request: MealPreviewRequest,
        trace_id: str | None = None,
    ) -> MealAnalysisResult:
        trace_id = trace_id or str(uuid.uuid4())
        local_now = request.consumed_at or datetime.now(timezone.utc)
        started = time.perf_counter()

        await _maybe_await(
            self.gateway.set_langfuse_context(
                session_id=f"meal_preview_{local_now.date().isoformat()}",
                user_id=patient_id,
            )
        )
        await _maybe_await(
            self.gateway.langfuse_trace_input(
                trace_id=trace_id,
                name="meal_analysis_preview",
                input_text=_summarize_request(request),
                metadata={
                    "agent": self.name,
                    "slot": request.slot.value,
                    "source": request.source.value,
                    "has_image": bool(request.image_url or request.image_urls),
                    "image_count": len(_collect_image_urls(request)),
                    "has_text": bool(request.text),
                    "has_items": bool(request.items),
                    "repeat_of_meal_id": (
                        str(request.repeat_of_meal_id)
                        if request.repeat_of_meal_id
                        else None
                    ),
                },
            )
        )

        t_ctx_start = time.perf_counter()
        context = await self._ctx.load(
            patient_id=patient_id, local_now=local_now
        )
        t_context_ms = int((time.perf_counter() - t_ctx_start) * 1000)

        t_extract_start = time.perf_counter()
        extraction = await self._resolve_extraction(
            patient_id=patient_id,
            request=request,
            context=context,
            trace_id=trace_id,
        )
        t_extract_ms = int((time.perf_counter() - t_extract_start) * 1000)

        gl = estimate_glycemic_load(extraction)

        t_parallel_start = time.perf_counter()
        (score_t, alts_t, glucose_t, plan_t, repeat_t) = await asyncio.gather(
            _timed(self._scorer.score(
                extraction=extraction,
                context=context,
                slot=request.slot.value,
                glycemic_load=gl,
                consumed_at=local_now.isoformat() if local_now else None,
                trace_id=trace_id,
            )),
            _timed(self._alternatives.rank(
                extraction=extraction,
                context=context,
                glycemic_load=gl,
                slot=request.slot.value,
                trace_id=trace_id,
            )),
            _timed(self._predict_glucose(
                patient_id=patient_id,
                extraction=extraction,
                context=context,
                glycemic_load=gl,
                slot=request.slot.value,
                trace_id=trace_id,
                meal_hour=local_now.hour if local_now else None,
            )),
            _timed(asyncio.to_thread(
                check_plan,
                extraction=extraction,
                slot=request.slot,
                active_plan=context.active_diet_plan,
            )),
            _timed(asyncio.to_thread(
                detect_repeat,
                extraction=extraction,
                context=context,
                slot=request.slot,
            )),
            return_exceptions=False,
        )
        t_parallel_ms = int((time.perf_counter() - t_parallel_start) * 1000)

        (score, t_score_ms) = score_t
        (alts_pairs, t_alts_ms) = alts_t
        (glucose, t_glucose_ms) = glucose_t
        (plan, t_plan_ms) = plan_t
        (repeat, t_repeat_ms) = repeat_t
        alternatives_list, pairings = alts_pairs

        result = MealAnalysisResult(
            extraction=extraction,
            score=score,
            alternatives=alternatives_list,
            pairings=pairings,
            predicted_glucose=glucose,
            plan=plan,
            repeat=repeat,
            generated_at=datetime.now(timezone.utc),
            model_trace_id=trace_id,
        )

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        await _maybe_await(
            self.gateway.langfuse_trace_output(
                trace_id=trace_id,
                output_text=_summarize_result(result),
                metadata={
                    "latency_ms": elapsed_ms,
                    "context_ms": t_context_ms,
                    "extract_ms": t_extract_ms,
                    "parallel_ms": t_parallel_ms,
                    "score_ms": t_score_ms,
                    "alternatives_ms": t_alts_ms,
                    "glucose_ms": t_glucose_ms,
                    "plan_ms": t_plan_ms,
                    "repeat_ms": t_repeat_ms,
                    "score": result.score.overall,
                    "glycemic_load": result.score.glycemic_load,
                    "alternatives_count": len(result.alternatives),
                    "has_prediction": result.predicted_glucose is not None,
                    "plan_compliant": result.plan.compliant,
                    "repeat_suggestion": result.repeat.suggestion.value,
                },
            )
        )

        return result

    async def _predict_glucose(
        self,
        *,
        patient_id: str,
        extraction: MealExtraction,
        context: Any,
        glycemic_load: float,
        slot: str,
        trace_id: str,
        meal_hour: int | None = None,
    ) -> GlucosePrediction | None:
        # ponytail: engine first, LLM fallback. No retry logic — if engine says None, LLM gets a shot.
        if self._metabolic:
            try:
                m = extraction.total_macros
                meal = self._metabolic.build_meal_dict(
                    {"carb": m.carbs, "protein": m.protein, "fiber": m.fiber, "cal": m.calories},
                    hour=meal_hour,
                )
                contract = await self._metabolic.assess(patient_id, meal)
                raw = self._metabolic.to_glucose_prediction(contract)
                if raw:
                    conf_map = {"high": ConfidenceLevel.HIGH, "medium": ConfidenceLevel.MEDIUM, "low": ConfidenceLevel.LOW}
                    return GlucosePrediction(
                        range_mg_dl_low=raw["range_mg_dl_low"],
                        range_mg_dl_high=raw["range_mg_dl_high"],
                        peak_minutes_after=raw["peak_minutes_after"],
                        confidence=conf_map.get(raw["confidence"], ConfidenceLevel.MEDIUM),
                        n_similar_meals=raw["n_similar_meals"],
                        evidence=raw.get("evidence", []),
                        rationale=raw["rationale"],
                    )
            except Exception:
                logger.exception("metabolic engine failed for %s, falling back to LLM", patient_id)

        return await self._glucose.predict(
            extraction=extraction,
            context=context,
            glycemic_load=glycemic_load,
            slot=slot,
            trace_id=trace_id,
        )

    async def quick_analyze(
        self,
        *,
        patient_id: str,
        request: MealPreviewRequest,
        trace_id: str | None = None,
    ) -> MealQuickResult:
        """Extract food items and nutrition only — no scoring or insights."""
        trace_id = trace_id or str(uuid.uuid4())
        local_now = request.consumed_at or datetime.now(timezone.utc)
        started = time.perf_counter()

        await _maybe_await(
            self.gateway.set_langfuse_context(
                session_id=f"meal_quick_{local_now.date().isoformat()}",
                user_id=patient_id,
            )
        )
        await _maybe_await(
            self.gateway.langfuse_trace_input(
                trace_id=trace_id,
                name="meal_quick_preview",
                input_text=_summarize_request(request),
                metadata={
                    "agent": self.name,
                    "mode": "quick",
                    "slot": request.slot.value,
                    "source": request.source.value,
                    "has_image": bool(request.image_url or request.image_urls),
                    "image_count": len(_collect_image_urls(request)),
                    "has_text": bool(request.text),
                    "has_items": bool(request.items),
                },
            )
        )

        context = await self._ctx.load(
            patient_id=patient_id, local_now=local_now
        )

        extraction = await self._resolve_extraction(
            patient_id=patient_id,
            request=request,
            context=context,
            trace_id=trace_id,
        )

        result = MealQuickResult(
            extraction=extraction,
            generated_at=datetime.now(timezone.utc),
            model_trace_id=trace_id,
        )

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        await _maybe_await(
            self.gateway.langfuse_trace_output(
                trace_id=trace_id,
                output_text=(
                    f"{extraction.name} | {len(extraction.items)} items | "
                    f"{extraction.total_macros.calories:.0f} kcal"
                ),
                metadata={
                    "latency_ms": elapsed_ms,
                    "mode": "quick",
                    "items_count": len(extraction.items),
                    "calories": extraction.total_macros.calories,
                },
            )
        )

        return result

    async def insights(
        self,
        *,
        patient_id: str,
        request: MealInsightsRequest,
        trace_id: str | None = None,
    ) -> MealAnalysisResult:
        """Score/alternatives/glucose/plan/repeat on an existing extraction."""
        trace_id = trace_id or str(uuid.uuid4())
        local_now = request.consumed_at or datetime.now(timezone.utc)
        started = time.perf_counter()

        await _maybe_await(
            self.gateway.set_langfuse_context(
                session_id=f"meal_insights_{local_now.date().isoformat()}",
                user_id=patient_id,
            )
        )
        await _maybe_await(
            self.gateway.langfuse_trace_input(
                trace_id=trace_id,
                name="meal_insights",
                input_text=f"{request.extraction.name} | slot={request.slot.value}",
                metadata={
                    "agent": self.name,
                    "mode": "insights",
                    "slot": request.slot.value,
                    "source": request.source.value,
                    "items_count": len(request.extraction.items),
                },
            )
        )

        t_ctx_start = time.perf_counter()
        context = await self._ctx.load(
            patient_id=patient_id, local_now=local_now
        )
        t_context_ms = int((time.perf_counter() - t_ctx_start) * 1000)

        extraction = request.extraction
        gl = estimate_glycemic_load(extraction)

        t_parallel_start = time.perf_counter()
        (score_t, alts_t, glucose_t, plan_t, repeat_t) = await asyncio.gather(
            _timed(self._scorer.score(
                extraction=extraction,
                context=context,
                slot=request.slot.value,
                glycemic_load=gl,
                consumed_at=local_now.isoformat() if local_now else None,
                trace_id=trace_id,
            )),
            _timed(self._alternatives.rank(
                extraction=extraction,
                context=context,
                glycemic_load=gl,
                slot=request.slot.value,
                trace_id=trace_id,
            )),
            _timed(self._predict_glucose(
                patient_id=patient_id,
                extraction=extraction,
                context=context,
                glycemic_load=gl,
                slot=request.slot.value,
                trace_id=trace_id,
                meal_hour=local_now.hour if local_now else None,
            )),
            _timed(asyncio.to_thread(
                check_plan,
                extraction=extraction,
                slot=request.slot,
                active_plan=context.active_diet_plan,
            )),
            _timed(asyncio.to_thread(
                detect_repeat,
                extraction=extraction,
                context=context,
                slot=request.slot,
            )),
            return_exceptions=False,
        )
        t_parallel_ms = int((time.perf_counter() - t_parallel_start) * 1000)

        (score, t_score_ms) = score_t
        (alts_pairs, t_alts_ms) = alts_t
        (glucose, t_glucose_ms) = glucose_t
        (plan, t_plan_ms) = plan_t
        (repeat, t_repeat_ms) = repeat_t
        alternatives_list, pairings = alts_pairs

        result = MealAnalysisResult(
            extraction=extraction,
            score=score,
            alternatives=alternatives_list,
            pairings=pairings,
            predicted_glucose=glucose,
            plan=plan,
            repeat=repeat,
            generated_at=datetime.now(timezone.utc),
            model_trace_id=trace_id,
        )

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        await _maybe_await(
            self.gateway.langfuse_trace_output(
                trace_id=trace_id,
                output_text=_summarize_result(result),
                metadata={
                    "latency_ms": elapsed_ms,
                    "mode": "insights",
                    "context_ms": t_context_ms,
                    "parallel_ms": t_parallel_ms,
                    "score_ms": t_score_ms,
                    "alternatives_ms": t_alts_ms,
                    "glucose_ms": t_glucose_ms,
                    "plan_ms": t_plan_ms,
                    "repeat_ms": t_repeat_ms,
                    "score": result.score.overall,
                    "glycemic_load": result.score.glycemic_load,
                    "alternatives_count": len(result.alternatives),
                    "has_prediction": result.predicted_glucose is not None,
                    "plan_compliant": result.plan.compliant,
                    "repeat_suggestion": result.repeat.suggestion.value,
                },
            )
        )

        return result

    # ── BaseAgent interface (prefer analyze() in new code) ───────────────

    async def run(self, input: AgentInput) -> AgentOutput:
        """Satisfy BaseAgent by unpacking a MealPreviewRequest from metadata.

        The primary typed API is ``analyze()``. This wrapper exists so the
        agent can be dispatched through generic foundation infrastructure.
        """
        patient_id = input.context.patient_id
        if not patient_id:
            return AgentOutput(
                message="patient_id is required for meal preview.",
                is_ready=False,
            )

        request_data = input.context.metadata.get("meal_preview")
        if request_data is None:
            return AgentOutput(
                message="meal_preview payload missing in context.metadata.",
                is_ready=False,
            )

        try:
            preview_request = MealPreviewRequest.model_validate(request_data)
        except Exception as exc:
            return AgentOutput(
                message=f"Invalid meal_preview payload: {exc}",
                is_ready=False,
            )

        result = await self.analyze(
            patient_id=patient_id,
            request=preview_request,
            trace_id=input.context.trace_id,
        )
        return AgentOutput(
            message=_summarize_result(result),
            is_ready=True,
            data=result.model_dump(mode="json"),
        )

    # ── extraction resolution ────────────────────────────────────────────

    async def _resolve_extraction(
        self,
        *,
        patient_id: str,
        request: MealPreviewRequest,
        context: Any,
        trace_id: str,
    ) -> MealExtraction:
        if request.repeat_of_meal_id is not None:
            prior = await _load_meal_from_qdrant(
                self._qdrant,
                str(request.repeat_of_meal_id),
                patient_id,
            )
            if prior is not None:
                return prior
            logger.warning(
                "repeat_of_meal_id=%s not found in Qdrant for %s; falling back to extractor",
                request.repeat_of_meal_id,
                patient_id,
            )

        all_images = _collect_image_urls(request)
        return await self._extractor.extract(
            context=context,
            slot=request.slot.value,
            image_urls=all_images or None,
            text=request.text,
            items=request.items,
            portion_note=request.portion_note,
            trace_id=trace_id,
        )


# ---------------------------------------------------------------------------
# Summary helpers for Langfuse trace I/O
# ---------------------------------------------------------------------------


def _collect_image_urls(request: MealPreviewRequest) -> list[str]:
    """Merge image_url + image_urls into one deduplicated list."""
    urls = list(request.image_urls or [])
    if request.image_url and request.image_url not in urls:
        urls.insert(0, request.image_url)
    return urls


def _summarize_request(request: MealPreviewRequest) -> str:
    parts: list[str] = [f"slot={request.slot.value}", f"source={request.source.value}"]
    img_count = len(_collect_image_urls(request))
    if img_count > 1:
        parts.append(f"images={img_count}")
    elif img_count == 1:
        parts.append("image")
    if request.text:
        parts.append(f"text={request.text[:120]}")
    if request.items:
        parts.append(f"items={len(request.items)}")
    if request.repeat_of_meal_id:
        parts.append(f"repeat_of={request.repeat_of_meal_id}")
    return " | ".join(parts)


def _summarize_result(result: MealAnalysisResult) -> str:
    pred = result.predicted_glucose
    pred_str = (
        f"peak {pred.range_mg_dl_low}-{pred.range_mg_dl_high} mg/dL"
        if pred
        else "no prediction"
    )
    return (
        f"{result.extraction.name} | score {result.score.overall} | "
        f"GL {result.score.glycemic_load:.1f} | "
        f"alternatives {len(result.alternatives)} | {pred_str}"
    )


# ---------------------------------------------------------------------------
# Helpers — load a previously saved meal into a MealExtraction
# ---------------------------------------------------------------------------


async def _load_meal_from_qdrant(
    retriever: QdrantRetriever, meal_id: str, patient_id: str
) -> MealExtraction | None:
    try:
        results = await retriever.retrieve_filtered(
            RetrievalRequest(
                query="",
                patient_ids=[patient_id],
                data_types=["meal"],
                limit=1,
                filters={"meal_id": meal_id},
            )
        )
        for r in results:
            if (r.data_type or r.payload.get("data_type")) != "meal":
                continue
            if r.payload.get("meal_id") != meal_id:
                continue
            return _extraction_from_meal_payload(r.payload)
        return None
    except Exception as exc:
        logger.warning("load_meal_from_qdrant(%s) failed: %s", meal_id, exc)
        return None


def _extraction_from_meal_payload(payload: dict[str, Any]) -> MealExtraction:
    nutrition = payload.get("nutrition") or {}
    items_raw = payload.get("items") or []

    items: list[ExtractedFoodItem] = []
    for it in items_raw:
        m = it.get("macro_nutritional_values") or {}
        items.append(
            ExtractedFoodItem(
                name=it.get("item_name") or "item",
                portion=float(it.get("serving_quantity") or 1),
                unit=it.get("serving_unit") or "serving",
                macros=MacroSet(
                    calories=float(m.get("calories") or 0),
                    carbs=float(m.get("carbohydrates") or 0),
                    carbs_simple=float(m.get("simple_carbs") or 0),
                    carbs_complex=float(m.get("complex_carbs") or 0),
                    fiber=float(m.get("fiber") or 0),
                    protein=float(m.get("proteins") or 0),
                    fat=float(m.get("fats") or 0),
                ),
                portion_confidence=ConfidenceLevel.HIGH,
            )
        )

    totals = MacroSet(
        calories=float(nutrition.get("calories") or 0),
        carbs=float(nutrition.get("carbohydrates") or 0),
        carbs_simple=float(nutrition.get("simple_carbs") or 0),
        carbs_complex=float(nutrition.get("complex_carbs") or 0),
        fiber=float(nutrition.get("fiber") or 0),
        protein=float(nutrition.get("proteins") or 0),
        fat=float(nutrition.get("fats") or 0),
    )

    return MealExtraction(
        name=payload.get("meal_name") or "Previous meal",
        items=items,
        total_macros=totals,
        tags=list(payload.get("tags") or []),
        overall_confidence=ConfidenceLevel.HIGH,
    )
