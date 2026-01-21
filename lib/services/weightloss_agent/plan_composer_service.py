"""Rule-based plan composer that assembles 4-week programs from intake + safety data."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from motor.motor_asyncio import AsyncIOMotorCollection
from pydantic import ValidationError
from decouple import config

from lib.guidelines.weightloss_agent.catalog import (
    GUIDELINE_CATALOG,
    get_metric,
    get_metric_sources,
)
from lib.schemas.weightloss_agent.plan_ai import AiPlanComposerResponse
from lib.schemas.weightloss_agent.plan import (
    HabitFocus,
    PlanGenerateRequest,
    PlanGenerateResponse,
    PlanMetricRange,
    PlanSnapshot,
    SafetyRuleCap,
)
from lib.services.ai_conversation_service.ai_conversation_service import (
    AiConversationService,
)
from lib.services.weightloss_agent.analytics_service import AnalyticsService
from lib.services.weightloss_agent.exercise_recommendation_service import (
    ExerciseRecommendationService,
)
from lib.services.weightloss_agent.intake_service import IntakeService
from lib.services.weightloss_agent.safety_rules_service import (
    SafetyRulesService,
)


class PlanComposerService:
    COMPOSER_VERSION = "v0.1.0"
    PLAN_DURATION_DAYS = 28
    PLAN_COMPOSER_MODE = "ai"
    REQUIRED_METRICS = [
        "daily_steps",
        "weekly_minutes_moderate",
        "protein_floor",
        "calorie_band",
        "hydration_oz",
    ]
    METRIC_HARD_BOUNDS: Dict[str, tuple[Optional[float], Optional[float]]] = {
        "daily_steps": (0, 20000),
        "weekly_minutes_moderate": (0, 600),
        "protein_floor": (0, 300),
        "calorie_band": (800, 4000),
        "hydration_oz": (0, 200),
    }

    def __init__(
        self,
        plan_snapshots_collection: AsyncIOMotorCollection,
        inbody_reports_collection: AsyncIOMotorCollection,
        intake_service: IntakeService,
        safety_rules_service: SafetyRulesService,
        analytics_service: AnalyticsService,
        exercise_recommendation_service: ExerciseRecommendationService,
        ai_conversation_service: AiConversationService,
    ) -> None:
        self.plan_snapshots_collection = plan_snapshots_collection
        self.inbody_reports_collection = inbody_reports_collection
        self.intake_service = intake_service
        self.safety_rules_service = safety_rules_service
        self.analytics_service = analytics_service
        self.exercise_recommendation_service = (
            exercise_recommendation_service
        )
        self.ai_conversation_service = ai_conversation_service
        self.enforce_intensity_caps = (
            str(config("WEIGHTLOSS_ENFORCE_INTENSITY_CAPS", default="true"))
            .strip()
            .lower()
            not in ("0", "false", "no", "off")
        )

    def _plan_mode(self) -> str:
        return self.PLAN_COMPOSER_MODE

    async def generate_plan(
        self, request: PlanGenerateRequest
    ) -> PlanGenerateResponse:
        context = await self._build_context(request.user_id)

        safety_summary = await self._build_safety_summary(
            request.user_id, context
        )

        if self._plan_mode() == "ai":
            plan_snapshot = await self._compose_plan_snapshot_ai(
                user_id=request.user_id,
                safety_summary=safety_summary,
                context=context,
            )
        else:
            plan_snapshot = self._compose_plan_snapshot(
                user_id=request.user_id,
                safety_summary=safety_summary,
                context=context,
            )

        if plan_snapshot.abstained:
            await self.analytics_service.emit_event(
                event_type="abstain_output",
                user_id=str(request.user_id),
                payload={"reason": plan_snapshot.abstain_reason},
                severity="warning",
            )
            return PlanGenerateResponse(
                abstained=True, reason=plan_snapshot.abstain_reason
            )

        await self._persist_plan(plan_snapshot)
        await self.analytics_service.emit_event(
            event_type="plan_generated",
            user_id=str(request.user_id),
            payload={"plan_id": str(plan_snapshot.plan_id)},
        )

        ai_recommendations = await self._build_ai_recommendations(
            request.user_id,
            context,
            safety_summary,
            plan_snapshot,
        )
        await self._persist_ai_recommendations(
            plan_snapshot.plan_id, ai_recommendations
        )

        return PlanGenerateResponse(
            plan_snapshot=plan_snapshot,
            ai_recommendations=ai_recommendations,
        )

    async def get_current_plan(
        self, user_id: UUID
    ) -> Optional[PlanSnapshot]:
        doc = await self.plan_snapshots_collection.find_one(
            {"user_id": str(user_id)}, sort=[("generated_at", -1)]
        )
        if not doc:
            return None
        return self._doc_to_plan_snapshot(doc)

    async def get_current_plan_details(
        self, user_id: UUID
    ) -> Optional[Dict[str, Any]]:
        doc = await self.plan_snapshots_collection.find_one(
            {"user_id": str(user_id)}, sort=[("generated_at", -1)]
        )
        if not doc:
            return None

        plan_snapshot = self._doc_to_plan_snapshot(doc)
        ai_recommendations = doc.get("ai_recommendations")

        if isinstance(ai_recommendations, dict) and (
            "parsed_content" in ai_recommendations
        ):
            ai_recommendations = await self._persist_ai_recommendations(
                plan_snapshot.plan_id, ai_recommendations
            )

        if not ai_recommendations and not plan_snapshot.abstained:
            context = await self._build_context(user_id)
            safety_summary = await self._build_safety_summary(
                user_id, context
            )
            raw_recommendations = await self._build_ai_recommendations(
                user_id,
                context,
                safety_summary,
                plan_snapshot,
            )
            ai_recommendations = await self._persist_ai_recommendations(
                plan_snapshot.plan_id, raw_recommendations
            )

        return {
            "plan_snapshot": plan_snapshot,
            "ai_recommendations": ai_recommendations,
        }

    async def get_context_snapshot(self, user_id: UUID) -> Dict[str, Any]:
        """Return the intake + safety context used for planning workflows."""
        return await self._build_context(user_id)

    async def _build_safety_summary(
        self, user_id: UUID, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        return await self.safety_rules_service.evaluate(
            {
                "user_id": str(user_id),
                "inbody": context.get("inbody", {}),
                "fitness": context.get("fitness", {}),
                "willingness": context.get("willingness", {}),
                "conditions": context.get("conditions", {}),
            }
        )

    async def _build_context(self, user_id: UUID) -> Dict[str, Any]:
        exercise = await self.intake_service.get_latest_exercise_preferences(
            user_id
        )
        fitness = await self.intake_service.get_latest_fitness_screen(user_id)
        willingness = await self.intake_service.get_latest_willingness(user_id)
        inbody = await self._get_latest_inbody(user_id)

        return {
            "exercise": exercise or {},
            "fitness": fitness or {},
            "willingness": willingness or {},
            "inbody": inbody or {},
            "conditions": (exercise or {}).get("conditions", {}),
        }

    async def _get_latest_inbody(self, user_id: UUID) -> Optional[Dict[str, Any]]:
        doc = await self.inbody_reports_collection.find_one(
            {"patient_id": str(user_id)}, sort=[("report_date", -1)]
        )
        if not doc:
            return None
        values = doc.get("values") or {}
        if not values:
            values = {}
            for measurement in doc.get("measurements", []):
                name = (measurement.get("measurement_type") or "").strip().lower()
                if not name:
                    continue
                normalized_key = name.replace(" ", "_")
                values[normalized_key] = measurement.get("value")

        derived = doc.get("derived") or {}
        parse_confidence = doc.get("parse_confidence") or {}

        return {
            "values": values,
            "derived": derived,
            "parse_confidence": parse_confidence,
        }

    def _compose_plan_snapshot(
        self,
        user_id: UUID,
        safety_summary: Dict[str, Any],
        context: Dict[str, Any],
    ) -> PlanSnapshot:
        missing_sources: List[str] = []
        targets: Dict[str, PlanMetricRange] = {}

        caps_lookup = {
            cap["metric"]: cap for cap in safety_summary.get("intensity_caps", [])
        }

        for metric_id in self.REQUIRED_METRICS:
            metric = get_metric(metric_id)
            if not metric:
                missing_sources.append(metric_id)
                continue
            sources = get_metric_sources(metric_id)
            if not sources:
                missing_sources.append(metric_id)
                continue
            min_value = metric.min_value
            max_value = metric.max_value

            cap = caps_lookup.get(metric_id)
            if cap and self.enforce_intensity_caps:
                max_value = min(max_value, cap.get("value", max_value))

            targets[metric_id] = PlanMetricRange(
                metric_id=metric.metric_id,
                label=metric.label,
                min_value=min_value,
                max_value=max_value,
                units=metric.units,
                cadence=metric.cadence,
                sources=sources,
            )

        if missing_sources:
            return PlanSnapshot(
                plan_id=uuid4(),
                user_id=user_id,
                generated_at=datetime.now(timezone.utc),
                valid_from=date.today(),
                valid_to=date.today() + timedelta(days=self.PLAN_DURATION_DAYS),
                hydration=PlanMetricRange(
                    metric_id="hydration_oz",
                    label="Hydration",
                    min_value=None,
                    max_value=None,
                    units="oz",
                    cadence="daily",
                    sources=[],
                ),
                targets={},
                habits_focus=[],
                safety_rules=[],
                sources=[],
                provenance=self._provenance(),
                abstained=True,
                abstain_reason=f"Missing guideline mapping for: {', '.join(missing_sources)}",
            )

        hydration_range = targets.pop("hydration_oz")
        safety_rules = [
            SafetyRuleCap(
                rule_id=cap["rule_id"],
                action=cap["type"],
                rationale_ids=[cap.get("rationale_source_id")],
                severity=cap.get("severity", "medium"),
                cap_value=cap.get("value"),
                units=cap.get("units"),
            )
            for cap in safety_summary.get("intensity_caps", [])
        ]

        habit_focus = self._build_habits()
        sources = list(
            {
                source
                for target in targets.values()
                for source in target.sources
            }
        )
        sources.extend(safety_summary.get("rationale_ids", []))
        sources = list({src for src in sources if src})

        snapshot = PlanSnapshot(
            plan_id=uuid4(),
            user_id=user_id,
            generated_at=datetime.now(timezone.utc),
            review_after_days=7,
            valid_from=date.today(),
            valid_to=date.today() + timedelta(days=self.PLAN_DURATION_DAYS),
            targets=targets,
            hydration=hydration_range,
            habits_focus=habit_focus,
            safety_rules=safety_rules,
            sources=sources,
            provenance=self._provenance(),
        )
        return snapshot

    def _extract_json_payload(self, raw: str) -> str:
        text = (raw or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 2 and lines[0].startswith("```"):
                fence_end = None
                for idx in range(1, len(lines)):
                    if lines[idx].startswith("```"):
                        fence_end = idx
                        break
                if fence_end is not None:
                    text = "\n".join(lines[1:fence_end]).strip()

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start : end + 1]
        return text

    def _build_ai_plan_prompt(
        self,
        context: Dict[str, Any],
        safety_summary: Dict[str, Any],
    ) -> str:
        allowed_metric_ids = list(self.REQUIRED_METRICS)
        guideline_ranges: Dict[str, Dict[str, Any]] = {}
        for metric_id in allowed_metric_ids:
            metric = get_metric(metric_id)
            if not metric:
                continue
            guideline_ranges[metric_id] = {
                "label": metric.label,
                "min_value": metric.min_value,
                "max_value": metric.max_value,
                "units": metric.units,
                "cadence": metric.cadence,
            }

        return f"""
Create personalized plan targets for the next 4 weeks.

Hard requirements:
- Output ONLY valid JSON (no markdown, no backticks) matching exactly:
  {{
    "targets": {{
      "<metric_id>": {{"min_value": number|null, "max_value": number|null}}
    }},
    "hydration_oz": {{"min_value": number|null, "max_value": number|null}},
    "habits": ["string", "..."]
  }}
- Allowed metric_ids (ONLY these): {allowed_metric_ids}
- Propose realistic, progressive targets. Avoid extreme or unsafe goals.
- Respect the safety caps/rules provided.
- Provide 2-4 habit statements that are specific and actionable.

Guideline reference ranges (starting point):
{json.dumps(guideline_ranges, indent=2)}

Patient context snapshot:
{json.dumps(context, indent=2, default=str)}

Safety evaluation:
{json.dumps(safety_summary, indent=2)}
""".strip()

    async def _compose_plan_snapshot_ai(
        self,
        user_id: UUID,
        safety_summary: Dict[str, Any],
        context: Dict[str, Any],
    ) -> PlanSnapshot:
        prompt = self._build_ai_plan_prompt(context, safety_summary)
        conversation_id = (
            f"plan_compose_{user_id}_{date.today().isoformat()}"
        )

        try:
            ai_message = await self.ai_conversation_service.generate_response(
                patient_id=str(user_id),
                user_id=str(user_id),
                conversation_id=conversation_id,
                human_input=prompt,
                conversation_type="other",
                additional_context={
                    "context": context,
                    "safety": safety_summary,
                },
                api_endpoint="/plan/generate",
            )
            payload_raw = self._extract_json_payload(
                (ai_message or {}).get("content") or ""
            )
            ai_output = AiPlanComposerResponse.model_validate(
                json.loads(payload_raw)
            )
        except (json.JSONDecodeError, ValidationError) as exc:
            print(f"AI plan parse/validation failed: {exc}")
            raise
        except Exception as exc:
            print(f"AI plan generation failed: {exc}")
            raise

        caps_lookup = {
            cap["metric"]: cap for cap in safety_summary.get("intensity_caps", [])
        }

        missing_sources: List[str] = []
        targets: Dict[str, PlanMetricRange] = {}

        def clamp(value: Optional[float], low: Optional[float], high: Optional[float]) -> Optional[float]:
            if value is None:
                return None
            if low is not None:
                value = max(value, low)
            if high is not None:
                value = min(value, high)
            return value

        for metric_id in self.REQUIRED_METRICS:
            if metric_id == "hydration_oz":
                continue
            metric = get_metric(metric_id)
            if not metric:
                missing_sources.append(metric_id)
                continue
            sources = get_metric_sources(metric_id)
            if not sources:
                missing_sources.append(metric_id)
                continue

            proposed = ai_output.targets.get(metric_id) or {}
            min_value = (
                proposed.min_value
                if proposed.min_value is not None
                else metric.min_value
            )
            max_value = (
                proposed.max_value
                if proposed.max_value is not None
                else metric.max_value
            )

            bound_low, bound_high = self.METRIC_HARD_BOUNDS.get(metric_id, (0, None))
            min_value = clamp(min_value, bound_low, bound_high)
            max_value = clamp(max_value, bound_low, bound_high)
            if min_value is not None and max_value is not None and min_value > max_value:
                min_value, max_value = max_value, min_value

            cap = caps_lookup.get(metric_id)
            if cap and self.enforce_intensity_caps and max_value is not None:
                max_value = min(max_value, cap.get("value", max_value))

            targets[metric_id] = PlanMetricRange(
                metric_id=metric.metric_id,
                label=metric.label,
                min_value=min_value,
                max_value=max_value,
                units=metric.units,
                cadence=metric.cadence,
                sources=sources,
            )

        if missing_sources:
            return PlanSnapshot(
                plan_id=uuid4(),
                user_id=user_id,
                generated_at=datetime.now(timezone.utc),
                valid_from=date.today(),
                valid_to=date.today() + timedelta(days=self.PLAN_DURATION_DAYS),
                hydration=PlanMetricRange(
                    metric_id="hydration_oz",
                    label="Hydration",
                    min_value=None,
                    max_value=None,
                    units="oz",
                    cadence="daily",
                    sources=[],
                ),
                targets={},
                habits_focus=[],
                safety_rules=[],
                sources=[],
                provenance=self._provenance(plan_mode="ai"),
                abstained=True,
                abstain_reason=f"Missing guideline mapping for: {', '.join(missing_sources)}",
            )

        hydration_metric = get_metric("hydration_oz")
        hydration_sources = get_metric_sources("hydration_oz")
        hydration_min = (
            ai_output.hydration_oz.min_value
            if ai_output.hydration_oz.min_value is not None
            else (hydration_metric.min_value if hydration_metric else None)
        )
        hydration_max = (
            ai_output.hydration_oz.max_value
            if ai_output.hydration_oz.max_value is not None
            else (hydration_metric.max_value if hydration_metric else None)
        )
        bound_low, bound_high = self.METRIC_HARD_BOUNDS.get("hydration_oz", (0, None))
        hydration_min = clamp(hydration_min, bound_low, bound_high)
        hydration_max = clamp(hydration_max, bound_low, bound_high)
        if hydration_min is not None and hydration_max is not None and hydration_min > hydration_max:
            hydration_min, hydration_max = hydration_max, hydration_min
        cap = caps_lookup.get("hydration_oz")
        if cap and self.enforce_intensity_caps and hydration_max is not None:
            hydration_max = min(hydration_max, cap.get("value", hydration_max))

        hydration_range = PlanMetricRange(
            metric_id="hydration_oz",
            label=(hydration_metric.label if hydration_metric else "Hydration"),
            min_value=hydration_min,
            max_value=hydration_max,
            units=(hydration_metric.units if hydration_metric else "oz"),
            cadence=(hydration_metric.cadence if hydration_metric else "daily"),
            sources=hydration_sources,
        )

        habit_texts = [
            habit.strip()
            for habit in (ai_output.habits or [])
            if habit and habit.strip()
        ]
        if not habit_texts:
            habits_focus = self._build_habits()
        else:
            habits_focus = [
                HabitFocus(
                    habit_id=f"ai_habit_{idx}",
                    description=text,
                    cue="daily",
                    measurement="self-report",
                    sources=["ai_plan"],
                    priority=idx + 1,
                )
                for idx, text in enumerate(habit_texts[:4])
            ]

        safety_rules = [
            SafetyRuleCap(
                rule_id=cap["rule_id"],
                action=cap["type"],
                rationale_ids=[cap.get("rationale_source_id")],
                severity=cap.get("severity", "medium"),
                cap_value=cap.get("value"),
                units=cap.get("units"),
            )
            for cap in safety_summary.get("intensity_caps", [])
        ]

        sources = list(
            {
                source
                for target in targets.values()
                for source in target.sources
            }
        )
        sources.extend(hydration_sources)
        sources.extend(safety_summary.get("rationale_ids", []))
        sources = list({src for src in sources if src})

        return PlanSnapshot(
            plan_id=uuid4(),
            user_id=user_id,
            generated_at=datetime.now(timezone.utc),
            review_after_days=7,
            valid_from=date.today(),
            valid_to=date.today() + timedelta(days=self.PLAN_DURATION_DAYS),
            targets=targets,
            hydration=hydration_range,
            habits_focus=habits_focus,
            safety_rules=safety_rules,
            sources=sources,
            provenance=self._provenance(plan_mode="ai"),
        )

    async def _build_ai_recommendations(
        self,
        user_id: UUID,
        context: Dict[str, Any],
        safety_summary: Dict[str, Any],
        plan_snapshot: PlanSnapshot,
    ) -> Optional[Dict[str, Any]]:
        if plan_snapshot.abstained:
            return None
        enriched_context = {**context, "safety": safety_summary}
        try:
            return await self.exercise_recommendation_service.generate_recommendations(
                user_id=user_id,
                context=enriched_context,
                plan_snapshot=plan_snapshot,
            )
        except Exception as exc:
            print(f"Failed to generate AI recommendations: {exc}")
            return None

    def _normalize_ai_recommendations(
        self, ai_recommendations: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        if not ai_recommendations:
            return None

        parsed_content = ai_recommendations.get("parsed_content")
        if not isinstance(parsed_content, dict):
            parsed_content = {}

        timeline = parsed_content.get("timeline")
        if not isinstance(timeline, list):
            timeline = []

        follow_up_questions = (
            ai_recommendations.get("follow_up_questions") or []
        )
        if not isinstance(follow_up_questions, list):
            follow_up_questions = []

        return {
            "intensity_level": parsed_content.get("intensity_level"),
            "notes": parsed_content.get("notes"),
            "timeline": timeline,
            "follow_up_questions": follow_up_questions,
        }

    async def _persist_ai_recommendations(
        self,
        plan_id: UUID,
        ai_recommendations: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        normalized = self._normalize_ai_recommendations(ai_recommendations)
        if normalized is None:
            return None

        await self.plan_snapshots_collection.update_one(
            {"plan_id": str(plan_id)},
            {"$set": {"ai_recommendations": normalized}},
        )
        return normalized

    async def _persist_plan(self, plan_snapshot: PlanSnapshot) -> None:
        doc = plan_snapshot.model_dump()
        doc["plan_id"] = str(plan_snapshot.plan_id)
        doc["user_id"] = str(plan_snapshot.user_id)
        doc["generated_at"] = doc["generated_at"].isoformat()
        doc["valid_from"] = doc["valid_from"].isoformat()
        doc["valid_to"] = doc["valid_to"].isoformat()

        def normalize_target(target: Dict[str, Any]) -> Dict[str, Any]:
            normalized = target.copy()
            cadence = normalized.get("cadence")
            if isinstance(cadence, date):
                normalized["cadence"] = cadence.isoformat()
            return normalized

        doc["targets"] = {
            key: normalize_target(value)
            for key, value in doc.get("targets", {}).items()
        }
        doc["hydration"] = normalize_target(doc["hydration"])

        await self.plan_snapshots_collection.insert_one(doc)

    def _build_habits(self) -> List[HabitFocus]:
        habits: List[HabitFocus] = []
        for guideline in GUIDELINE_CATALOG.values():
            for idx, habit in enumerate(guideline.focus_habits):
                habits.append(
                    HabitFocus(
                        habit_id=f"{guideline.guideline_id}_habit_{idx}",
                        description=habit,
                        cue="daily",
                        measurement="self-report",
                        sources=[guideline.guideline_id],
                        priority=idx + 1,
                    )
                )
        # Ensure at least two habits
        return habits[:2] if habits else []

    def _doc_to_plan_snapshot(self, doc: Dict[str, Any]) -> PlanSnapshot:
        targets = {
            key: PlanMetricRange(**value)
            for key, value in doc.get("targets", {}).items()
        }
        hydration = PlanMetricRange(**doc["hydration"])
        habits = [HabitFocus(**habit) for habit in doc.get("habits_focus", [])]
        safety_rules = [
            SafetyRuleCap(**rule) for rule in doc.get("safety_rules", [])
        ]
        return PlanSnapshot(
            plan_id=UUID(doc["plan_id"]),
            user_id=UUID(doc["user_id"]),
            generated_at=doc["generated_at"],
            review_after_days=doc.get("review_after_days", 7),
            valid_from=doc["valid_from"],
            valid_to=doc["valid_to"],
            targets=targets,
            hydration=hydration,
            habits_focus=habits,
            safety_rules=safety_rules,
            sources=doc.get("sources", []),
            provenance=doc.get("provenance", {}),
        )

    def _provenance(self, plan_mode: str = "rule_based") -> Dict[str, Any]:
        return {
            "composer_version": self.COMPOSER_VERSION,
            "plan_mode": plan_mode,
        }
