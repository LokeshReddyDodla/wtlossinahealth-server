"""Coach messenger surfaces nudges/timers sourced from plan targets."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID, uuid4

from motor.motor_asyncio import AsyncIOMotorCollection

from lib.schemas.weightloss_agent.coach import (
    CoachActionRequest,
    CoachActionResponse,
    SuggestionCard,
)
from lib.schemas.weightloss_agent.plan import (
    PlanGenerateRequest,
    PlanMetricRange,
    PlanSnapshot,
)
from lib.services.weightloss_agent.analytics_service import AnalyticsService
from lib.services.weightloss_agent.plan_composer_service import (
    PlanComposerService,
)


class CoachMessengerService:
    def __init__(
        self,
        suggestion_cards_collection: AsyncIOMotorCollection,
        plan_composer_service: PlanComposerService,
        analytics_service: AnalyticsService,
    ) -> None:
        self.suggestion_cards_collection = suggestion_cards_collection
        self.plan_composer_service = plan_composer_service
        self.analytics_service = analytics_service

    async def act(
        self, request: CoachActionRequest
    ) -> CoachActionResponse:
        plan = await self.plan_composer_service.get_current_plan(
            request.user_id
        )
        if not plan:
            plan_response = await self.plan_composer_service.generate_plan(
                PlanGenerateRequest(user_id=request.user_id)
            )
            plan = plan_response.plan_snapshot if plan_response else None

        if not plan:
            await self.analytics_service.emit_event(
                event_type="abstain_output",
                user_id=str(request.user_id),
                payload={"reason": "No active plan to coach against"},
                severity="warning",
            )
            return CoachActionResponse(
                cards=[], abstained=True, reason="No plan"
            )

        cards = await self._build_cards(request, plan)
        if not cards:
            await self.analytics_service.emit_event(
                event_type="abstain_output",
                user_id=str(request.user_id),
                payload={"reason": "Coach messenger did not map any cards"},
                severity="warning",
            )
            return CoachActionResponse(
                cards=[], abstained=True, reason="No cards"
            )

        for card in cards:
            await self._persist_card(card)

        await self.analytics_service.emit_event(
            event_type="coach_action_sent",
            user_id=str(request.user_id),
            payload={
                "card_ids": [str(card.card_id) for card in cards],
                "trigger": request.trigger,
            },
        )

        return CoachActionResponse(cards=cards, abstained=False, reason=None)

    async def _persist_card(self, card: SuggestionCard) -> None:
        doc = card.model_dump()
        doc["card_id"] = str(card.card_id)
        doc["user_id"] = str(card.user_id)
        await self.suggestion_cards_collection.insert_one(doc)

    async def _build_cards(
        self, request: CoachActionRequest, plan: PlanSnapshot
    ) -> List[SuggestionCard]:
        cards: List[SuggestionCard] = []
        base_tags = request.context_tags or []
        def _format_metric_range(metric: Optional[PlanMetricRange]) -> str:
            if not metric:
                return ""
            low = (
                metric.min_value
                if metric.min_value is not None
                else metric.max_value
                or 0
            )
            high = (
                metric.max_value
                if metric.max_value is not None
                else metric.min_value
                or low
            )
            if low == high:
                return f"{low:.0f} {metric.units}".strip()
            return f"{low:.0f}-{high:.0f} {metric.units}".strip()
        if plan.hydration.min_value and plan.hydration.max_value:
            cards.append(
                SuggestionCard(
                    card_id=uuid4(),
                    user_id=request.user_id,
                    card_type="nudge",
                    title="Hydration focus",
                    body=(
                        f"Plan hydration target: "
                        f"{plan.hydration.min_value:.0f}-{plan.hydration.max_value:.0f}{plan.hydration.units}. "
                        "Log your first glass within 30 minutes of waking."
                    ),
                    context_tags=base_tags + ["hydration", "morning"],
                    sources=plan.hydration.sources,
                    confidence=0.72,
                    created_at=datetime.now(timezone.utc),
                    provenance={"component": "coach_messenger"},
                )
            )

        steps_target = plan.targets.get("daily_steps")
        if steps_target:
            cards.append(
                SuggestionCard(
                    card_id=uuid4(),
                    user_id=request.user_id,
                    card_type="timer",
                    title="Post-meal walk timer",
                    body=(
                        f"Your daily step range is "
                        f"{steps_target.min_value:.0f}-{steps_target.max_value:.0f} {steps_target.units}. "
                        "Start a 10-minute timer after lunch."
                    ),
                    context_tags=base_tags + ["steps", "post-meal"],
                    sources=steps_target.sources,
                    confidence=0.64,
                    created_at=datetime.now(timezone.utc),
                    provenance={"component": "coach_messenger"},
                )
            )

        minutes_target = plan.targets.get("weekly_minutes_moderate")
        if minutes_target:
            habit = plan.habits_focus[0].description if plan.habits_focus else "alternate bike + core sessions"
            target_minutes = minutes_target.min_value or minutes_target.max_value or 30
            block_minutes = max(20, min(int(target_minutes), 45))
            minutes_range = _format_metric_range(minutes_target)
            cards.append(
                SuggestionCard(
                    card_id=uuid4(),
                    user_id=request.user_id,
                    card_type="nudge",
                    title="Today's workout block",
                    body=(
                        f"Schedule a {block_minutes}-minute moderate block today. "
                        f"Try: {habit}. You're chasing {minutes_range} this week."
                    ),
                    context_tags=base_tags + ["exercise", "moderate"],
                    sources=minutes_target.sources,
                    confidence=0.68,
                    created_at=datetime.now(timezone.utc),
                    provenance={"component": "coach_messenger"},
                )
            )

        protein_target = plan.targets.get("protein_floor")
        calorie_target = plan.targets.get("calorie_band")
        if protein_target or calorie_target:
            protein_text = (
                _format_metric_range(protein_target) if protein_target else "steady protein"
            )
            calorie_text = (
                _format_metric_range(calorie_target) if calorie_target else "a steady calorie window"
            )
            cards.append(
                SuggestionCard(
                    card_id=uuid4(),
                    user_id=request.user_id,
                    card_type="nudge",
                    title="Log meals + macros",
                    body=(
                        f"Track meals in the app today. Aim for {protein_text} "
                        f"and keep calories within {calorie_text}. "
                        "Flag any low-protein meals so we can rebalance dinner."
                    ),
                    context_tags=base_tags + ["nutrition", "tracking"],
                    sources=(
                        (protein_target.sources if protein_target else [])
                        + (calorie_target.sources if calorie_target else [])
                    ),
                    confidence=0.66,
                    created_at=datetime.now(timezone.utc),
                    provenance={"component": "coach_messenger"},
                )
            )

        habits = plan.habits_focus[:2]
        for habit in habits:
            cards.append(
                SuggestionCard(
                    card_id=uuid4(),
                    user_id=request.user_id,
                    card_type="reminder",
                    title=f"Habit focus: {habit.habit_id.split('_')[-1].title()}",
                    body=habit.description,
                    context_tags=base_tags + ["habit"],
                    sources=habit.sources,
                    confidence=0.6,
                    created_at=datetime.now(timezone.utc),
                    provenance={"component": "coach_messenger"},
                )
            )

        if len(cards) < 2:
            cards.append(
                SuggestionCard(
                    card_id=uuid4(),
                    user_id=request.user_id,
                    card_type="nudge",
                    title="Check-in",
                    body="Review today's plan targets and log one win before bed.",
                    context_tags=base_tags + ["check-in"],
                    sources=[],
                    confidence=0.5,
                    created_at=datetime.now(timezone.utc),
                    provenance={"component": "coach_messenger"},
                )
            )

        return cards[:6]
