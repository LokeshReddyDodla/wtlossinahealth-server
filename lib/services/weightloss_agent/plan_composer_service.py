"""Rule-based plan composer that assembles 4-week programs from intake + safety data."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from motor.motor_asyncio import AsyncIOMotorCollection

from lib.guidelines.weightloss_agent.catalog import (
    GUIDELINE_CATALOG,
    get_metric,
    get_metric_sources,
)
from lib.schemas.weightloss_agent.plan import (
    HabitFocus,
    PlanGenerateRequest,
    PlanGenerateResponse,
    PlanMetricRange,
    PlanSnapshot,
    SafetyRuleCap,
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
    REQUIRED_METRICS = [
        "daily_steps",
        "weekly_minutes_moderate",
        "protein_floor",
        "calorie_band",
        "hydration_oz",
    ]

    def __init__(
        self,
        plan_snapshots_collection: AsyncIOMotorCollection,
        inbody_reports_collection: AsyncIOMotorCollection,
        intake_service: IntakeService,
        safety_rules_service: SafetyRulesService,
        analytics_service: AnalyticsService,
        exercise_recommendation_service: ExerciseRecommendationService,
    ) -> None:
        self.plan_snapshots_collection = plan_snapshots_collection
        self.inbody_reports_collection = inbody_reports_collection
        self.intake_service = intake_service
        self.safety_rules_service = safety_rules_service
        self.analytics_service = analytics_service
        self.exercise_recommendation_service = (
            exercise_recommendation_service
        )

    async def generate_plan(
        self, request: PlanGenerateRequest
    ) -> PlanGenerateResponse:
        context = await self._build_context(request.user_id)

        safety_summary = await self.safety_rules_service.evaluate(
            {
                "user_id": str(request.user_id),
                "inbody": context.get("inbody", {}),
                "fitness": context.get("fitness", {}),
                "willingness": context.get("willingness", {}),
                "conditions": context.get("conditions", {}),
            }
        )

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

    async def get_context_snapshot(self, user_id: UUID) -> Dict[str, Any]:
        """Return the intake + safety context used for planning workflows."""
        return await self._build_context(user_id)

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
            if cap:
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

    def _provenance(self) -> Dict[str, Any]:
        return {"composer_version": self.COMPOSER_VERSION}
