"""Generates AI-powered exercise recommendations using stored intake + safety context."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional
from uuid import UUID

from lib.schemas.weightloss_agent.plan import PlanSnapshot
from lib.services.ai_conversation_service.ai_conversation_service import (
    AiConversationService,
)


class ExerciseRecommendationService:
    def __init__(
        self,
        ai_conversation_service: AiConversationService,
    ) -> None:
        self.ai_conversation_service = ai_conversation_service

    async def generate_recommendations(
        self,
        user_id: UUID,
        context: Dict[str, Any],
        plan_snapshot: PlanSnapshot,
    ) -> Optional[Dict[str, Any]]:
        prompt = self._build_prompt(context, plan_snapshot)
        try:
            ai_message = await self.ai_conversation_service.generate_response(
                patient_id=str(user_id),
                user_id=str(user_id),
                conversation_id=f"plan_rec_{user_id}_{plan_snapshot.plan_id}",
                human_input=prompt,
                conversation_type="weight-loss-agent",
                additional_context={
                    "plan_snapshot": plan_snapshot.model_dump(),
                    "exercise_preferences": context.get("exercise"),
                    "fitness_screen": context.get("fitness"),
                    "willingness": context.get("willingness"),
                    "safety": context.get("safety"),
                },
            )
            return {
                "message_id": ai_message.get("_id"),
                "content": ai_message.get("content"),
                "confidence": (ai_message.get("metadata") or {}).get(
                    "confidence_score"
                ),
                "follow_up_questions": ai_message.get(
                    "follow_up_questions", []
                ),
                "tags": (ai_message.get("metadata") or {}).get("tags", []),
            }
        except Exception as exc:
            # Log failure upstream; fall back to None so API still returns plan
            print(f"Exercise recommendation generation failed: {exc}")
            return None

    def _build_prompt(
        self, context: Dict[str, Any], plan_snapshot: PlanSnapshot
    ) -> str:
        preferences = context.get("exercise") or {}
        availability = preferences.get("availability", [])
        safety = context.get("safety") or {}
        safety_notes = []
        for contraindication in safety.get("contraindications", []):
            safety_notes.append(
                f"- Avoid {contraindication.get('metric')} "
                f"(rule {contraindication.get('rule_id')})"
            )
        for cap in safety.get("intensity_caps", []):
            safety_notes.append(
                f"- Cap {cap.get('metric')} at {cap.get('value')} "
                f"{cap.get('units')}"
            )

        availability_str = "\n".join(
            f"- {slot.get('day_of_week', '').title()}: "
            f"{slot.get('start_local_time')} to {slot.get('end_local_time')}"
            for slot in availability
        )
        if not availability_str:
            availability_str = "Not provided"

        plan_targets = "\n".join(
            f"* {metric_id}: {target.min_value}-{target.max_value} {target.units}"
            for metric_id, target in plan_snapshot.targets.items()
        )

        prompt = f"""
Using the verified intake, willingness, and safety review, craft specific exercise sessions the coach should send.

Patient context:
- Preferred modalities: {preferences.get('preferred_modalities', [])}
- Avoid modalities: {preferences.get('avoid_modalities', [])}
- Environments: {preferences.get('environments', [])}
- Equipment on hand: {preferences.get('equipment_available', [])}
- Weekly availability:
{availability_str}
- Barriers: {preferences.get('barriers', [])}
- Motivators: {preferences.get('motivators', [])}

Safety guidance:
{os.linesep.join(safety_notes) if safety_notes else 'No special restrictions beyond general guidelines.'}

Plan targets for the next 4 weeks:
{plan_targets}

Deliver:
1. Three concrete workout blocks (title + duration + short steps) aligned with preferences.
2. Highlight how each block respects the plan targets and safety caps.
3. Suggest one accountability nudge referencing the motivators.

Keep tone encouraging, actionable, and specific to the supplied context.
"""
        return prompt.strip()
