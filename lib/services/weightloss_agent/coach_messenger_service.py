"""Coach messenger surfaces nudges/timers sourced from plan targets."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from motor.motor_asyncio import AsyncIOMotorCollection
from pydantic import ValidationError

from lib.schemas.weightloss_agent.coach import (
    CoachActionRequest,
    CoachActionResponse,
    SuggestionCard,
)
from lib.schemas.weightloss_agent.coach_ai import AiCoachCardsResponse
from lib.schemas.weightloss_agent.plan import (
    PlanGenerateRequest,
    PlanMetricRange,
    PlanSnapshot,
)
from lib.services.ai_conversation_service.ai_conversation_service import (
    AiConversationService,
)
from lib.services.weightloss_agent.analytics_service import AnalyticsService
from lib.services.weightloss_agent.plan_composer_service import (
    PlanComposerService,
)


class CoachMessengerService:
    COACH_MESSENGER_MODE = "ai"

    def __init__(
        self,
        suggestion_cards_collection: AsyncIOMotorCollection,
        plan_composer_service: PlanComposerService,
        analytics_service: AnalyticsService,
        ai_conversation_service: AiConversationService,
    ) -> None:
        self.suggestion_cards_collection = suggestion_cards_collection
        self.plan_composer_service = plan_composer_service
        self.analytics_service = analytics_service
        self.ai_conversation_service = ai_conversation_service

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

    def _coach_cards_mode(self) -> str:
        return self.COACH_MESSENGER_MODE

    async def _persist_card(self, card: SuggestionCard) -> None:
        doc = card.model_dump()
        doc["card_id"] = str(card.card_id)
        doc["user_id"] = str(card.user_id)
        await self.suggestion_cards_collection.insert_one(doc)

    async def _build_cards(
        self, request: CoachActionRequest, plan: PlanSnapshot
    ) -> List[SuggestionCard]:
        if self._coach_cards_mode() == "ai":
            return await self._build_cards_ai(request, plan)
        return await self._build_cards_rule_based(request, plan)

    async def _recent_cards_context(
        self, user_id: UUID, limit: int = 12
    ) -> List[Dict[str, Any]]:
        cursor = (
            self.suggestion_cards_collection.find(
                {"user_id": str(user_id)},
                projection={
                    "_id": 0,
                    "title": 1,
                    "body": 1,
                    "card_type": 1,
                    "context_tags": 1,
                    "created_at": 1,
                },
            )
            .sort("created_at", -1)
            .limit(limit)
        )
        results = await cursor.to_list(length=limit)
        return [
            {
                "card_type": item.get("card_type"),
                "title": item.get("title"),
                "body": item.get("body"),
                "context_tags": item.get("context_tags", []),
            }
            for item in results
        ]

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

        # If wrapped with extra prose, try to extract the first JSON object.
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start : end + 1]
        return text

    async def _build_cards_ai(
        self, request: CoachActionRequest, plan: PlanSnapshot
    ) -> List[SuggestionCard]:
        base_tags = request.context_tags or []
        metric_ids = ["hydration_oz", *sorted(plan.targets.keys())]
        habit_ids = [habit.habit_id for habit in plan.habits_focus]
        recent_cards = await self._recent_cards_context(request.user_id)

        plan_targets_context = {
            metric_id: {
                "min_value": target.min_value,
                "max_value": target.max_value,
                "units": target.units,
                "cadence": target.cadence,
            }
            for metric_id, target in plan.targets.items()
        }
        hydration_context = {
            "min_value": plan.hydration.min_value,
            "max_value": plan.hydration.max_value,
            "units": plan.hydration.units,
            "cadence": plan.hydration.cadence,
        }

        prompt = f"""
Generate 3-6 coaching suggestion cards for a weight loss patient.

Hard requirements:
- Output ONLY valid JSON (no markdown, no backticks) matching:
  {{"cards":[{{"card_type":"nudge|timer|reminder|meal|pantry","title":str,"body":str,"cta":str|null,"context_tags":[str],"metric_ids":[str],"habit_ids":[str],"confidence":0-1|null}}]}}
- Keep each title <= 80 chars and body <= 240 chars.
- No medication/supplement advice. No diagnosis. No medical claims.
- Avoid repetition: do not rephrase the same idea as any of the recent cards.
- Grounding: `metric_ids` must be a subset of {metric_ids}. `habit_ids` must be a subset of {habit_ids}.
- Make suggestions actionable, varied, and aligned with the plan targets.

Trigger: {request.trigger}
Base context tags to include: {base_tags}

Plan snapshot (ground truth):
- Targets: {json.dumps(plan_targets_context, ensure_ascii=False)}
- Hydration: {json.dumps(hydration_context, ensure_ascii=False)}
- Habit focus: {json.dumps([habit.model_dump() for habit in plan.habits_focus], ensure_ascii=False)}
- Safety caps/notes: {json.dumps([rule.model_dump() for rule in plan.safety_rules], ensure_ascii=False)}

Recent cards to avoid repeating:
{recent_cards}
""".strip()

        conversation_id = (
            f"coach_cards_{request.user_id}_{plan.plan_id}_{request.trigger}"
        )
        try:
            ai_message = await self.ai_conversation_service.generate_response(
                patient_id=str(request.user_id),
                user_id=str(request.user_id),
                conversation_id=conversation_id,
                human_input=prompt,
                conversation_type="other",
                additional_context={
                    "plan_snapshot": plan.model_dump(),
                    "trigger": request.trigger,
                    "base_context_tags": base_tags,
                    "recent_cards": recent_cards,
                },
                api_endpoint="/coach/act",
            )
        except Exception as exc:
            print(f"AI coach cards generation failed: {exc}")
            raise

        payload_raw = self._extract_json_payload(ai_message.get("content") or "")
        try:
            parsed = AiCoachCardsResponse.model_validate(json.loads(payload_raw))
        except (json.JSONDecodeError, ValidationError) as exc:
            print(f"AI coach cards parse/validation failed: {exc}")
            raise

        cards: List[SuggestionCard] = []
        for item in parsed.cards[:6]:
            sources: List[str] = []
            for metric_id in item.metric_ids:
                if metric_id == "hydration_oz":
                    sources.extend(plan.hydration.sources)
                else:
                    target = plan.targets.get(metric_id)
                    if target:
                        sources.extend(target.sources)
            for habit_id in item.habit_ids:
                habit = next(
                    (h for h in plan.habits_focus if h.habit_id == habit_id),
                    None,
                )
                if habit:
                    sources.extend(habit.sources)
            sources = list({src for src in sources if src})

            context_tags = list(
                {
                    *(base_tags or []),
                    *(item.context_tags or []),
                }
            )

            cards.append(
                SuggestionCard(
                    card_id=uuid4(),
                    user_id=request.user_id,
                    card_type=item.card_type,
                    title=item.title,
                    body=item.body,
                    cta=item.cta,
                    context_tags=context_tags,
                    sources=sources,
                    confidence=item.confidence if item.confidence is not None else 0.65,
                    created_at=datetime.now(timezone.utc),
                    provenance={"component": "coach_messenger_ai"},
                )
            )

        return cards

    async def _build_cards_rule_based(
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
