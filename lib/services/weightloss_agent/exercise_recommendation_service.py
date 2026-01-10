"""Generates AI-powered exercise recommendations using stored intake + safety context."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional
from uuid import UUID

from lib.schemas.weightloss_agent.plan import PlanSnapshot
from lib.services.ai_conversation_service.ai_conversation_service import (
    AiConversationService,
)
from lib.utils.json_parsing import parse_json_garbage


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
                    "plan_snapshot": plan_snapshot.model_dump(mode="json"),
                    "exercise_preferences": context.get("exercise"),
                    "fitness_screen": context.get("fitness"),
                    "willingness": context.get("willingness"),
                },
                api_endpoint="/plan/exercise-recommendations",
            )
            content = ai_message.get("content") or ""
            parsed_content = self._parse_json_content(content)
            return {
                "message_id": ai_message.get("_id"),
                "content": content,
                "parsed_content": parsed_content,
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
        willingness = context.get("willingness") or {}

        def normalize_day(value: str) -> str:
            normalized = (value or "").strip()
            if not normalized:
                return ""
            key = normalized.lower()
            day_map = {
                "mon": "Monday",
                "monday": "Monday",
                "tue": "Tuesday",
                "tues": "Tuesday",
                "tuesday": "Tuesday",
                "wed": "Wednesday",
                "wednesday": "Wednesday",
                "thu": "Thursday",
                "thur": "Thursday",
                "thurs": "Thursday",
                "thursday": "Thursday",
                "fri": "Friday",
                "friday": "Friday",
                "sat": "Saturday",
                "saturday": "Saturday",
                "sun": "Sunday",
                "sunday": "Sunday",
            }
            return day_map.get(key, normalized.title())

        availability_str = "\n".join(
            f"- {normalize_day(slot.get('day_of_week', ''))}: "
            f"{slot.get('start_local_time')} to {slot.get('end_local_time')}"
            for slot in availability
            if slot.get("day_of_week")
        )
        if not availability_str:
            availability_str = "Not provided"

        preferred_workout_days = preferences.get("preferred_workout_days") or []
        if isinstance(preferred_workout_days, str):
            preferred_workout_days = [preferred_workout_days]
        preferred_workout_days = [
            normalize_day(day)
            for day in preferred_workout_days
            if day and normalize_day(day)
        ]
        if not preferred_workout_days and availability:
            preferred_workout_days = [
                normalize_day(slot.get("day_of_week", ""))
                for slot in availability
                if normalize_day(slot.get("day_of_week", ""))
            ]
        preferred_workout_days_str = (
            ", ".join(dict.fromkeys(preferred_workout_days))
            if preferred_workout_days
            else "Not provided"
        )

        equipment_available = (
            preferences.get("available_equipment")
            or preferences.get("equipment_available")
            or []
        )
        if isinstance(equipment_available, str):
            equipment_available = [equipment_available]
        equipment_list = [
            str(item).strip()
            for item in equipment_available
            if str(item).strip()
        ]
        equipment_lower = [item.lower() for item in equipment_list]
        has_dumbbells = any("dumbbell" in item for item in equipment_lower)
        has_bands = any("band" in item for item in equipment_lower)
        has_bodyweight = any(
            item in ("bodyweight", "body weight", "no equipment")
            or "bodyweight" in item
            for item in equipment_lower
        )
        if not equipment_list:
            has_bodyweight = True
        equipment_focus = (
            f"dumbbells: {'yes' if has_dumbbells else 'no'}, "
            f"rubber bands: {'yes' if has_bands else 'no'}, "
            f"bodyweight: {'yes' if has_bodyweight else 'no'}"
        )

        preferred_workout_type = preferences.get("preferred_workout_type")
        if not preferred_workout_type:
            modalities = preferences.get("preferred_modalities", [])
            preferred_workout_type = (
                ", ".join(modalities) if modalities else "Not provided"
            )

        user_selected_exercises = (
            preferences.get("user_selected_exercises") or []
        )
        if isinstance(user_selected_exercises, str):
            user_selected_exercises = [user_selected_exercises]
        user_selected_exercises_str = (
            ", ".join(user_selected_exercises)
            if user_selected_exercises
            else "None"
        )

        inbody = context.get("inbody") or {}
        inbody_values = inbody.get("values") or {}
        inbody_derived = inbody.get("derived") or {}

        def pick_metric(*keys: str) -> Optional[Any]:
            for key in keys:
                value = inbody_values.get(key)
                if value not in (None, ""):
                    return value
                value = inbody_derived.get(key)
                if value not in (None, ""):
                    return value
            return None

        bmi_value = pick_metric("bmi", "bmi_value")
        bmr_value = pick_metric(
            "basal_metabolic_rate", "bmr", "bmr_kcal"
        )
        visceral_fat_value = pick_metric(
            "visceral_fat_level", "visceral_fat"
        )

        def format_metric(value: Any) -> str:
            return str(value) if value not in (None, "") else "Not available"

        plan_targets = "\n".join(
            f"* {metric_id}: {target.min_value}-{target.max_value} {target.units}"
            for metric_id, target in plan_snapshot.targets.items()
        )
        if not plan_targets:
            plan_targets = "Not provided"

        prompt = f"""
Create a personalized 7-day workout routine timeline as JSON.

Hard requirements:
- Output ONLY valid JSON (no markdown, no backticks).
- Timeline must include all 7 days Monday-Sunday, in order.
- Use preferred_workout_days to set is_workout_day. If the list includes patterns like "Weekends only", map to Saturday/Sunday. If preferred_workout_days is empty, infer from availability.
- Non-workout days must have exercises: [] and a light activity daily_target (steps or recovery).
- Each workout day should include 3-6 exercises with sets/reps or duration_minutes.
- Use only available equipment (dumbbells, rubber bands, bodyweight) and include user_selected_exercises when possible.
- Auto-calculate intensity_level from BMI, BMR, visceral fat, and goals (plan targets + weekly minutes promised). Do NOT use any manual intensity input.
- Keep daily_target and motivator to 1-2 short sentences.
- Do not include calorie or protein targets in the daily timeline.

Output schema (exact keys):
{{
  "timeline": [
    {{
      "day": "Monday",
      "is_workout_day": true,
      "exercises": [
        {{"name": "Exercise", "sets": 3, "reps": 12, "duration_minutes": null, "equipment": "Dumbbells"}}
      ],
      "daily_target": "string",
      "motivator": "string"
    }}
  ],
  "intensity_level": "Calculated: Moderate",
  "notes": "string"
}}

Patient context:
- Preferred workout type: {preferred_workout_type}
- Preferred modalities: {preferences.get('preferred_modalities', [])}
- Avoid modalities: {preferences.get('avoid_modalities', [])}
- Environments: {preferences.get('environments', [])}
- Available equipment: {equipment_list}
- Equipment focus: {equipment_focus}
- Preferred workout days: {preferred_workout_days_str}
- Weekly availability:
{availability_str}
- Session length target: {preferences.get('session_length_minutes', 'Not provided')} minutes
- Weekly session target: {preferences.get('weekly_session_target', 'Not provided')}
- User-selected exercises: {user_selected_exercises_str}
- Barriers: {preferences.get('barriers', [])}
- Motivators: {preferences.get('motivators', [])}
- Caregiver notes: {preferences.get('caregiver_notes') or 'None'}
- Readiness stage: {willingness.get('readiness_stage') or 'Not provided'}
- Weekly minutes promised: {willingness.get('weekly_minutes_promised') or 'Not provided'}
- Commitment score: {willingness.get('commitment_score') or 'Not provided'}
- Physical metrics (latest): BMI {format_metric(bmi_value)}, BMR {format_metric(bmr_value)}, Visceral Fat {format_metric(visceral_fat_value)}

Plan targets for the next 4 weeks:
{plan_targets}
"""
        return prompt.strip()

    def _parse_json_content(
        self, content: str
    ) -> Optional[Dict[str, Any]]:
        if not content:
            return None
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
            return None
        except json.JSONDecodeError:
            pass
        try:
            parsed = parse_json_garbage(content)
        except Exception:
            return None
        if isinstance(parsed, dict):
            return parsed
        return None
