"""Text representation builders for diet and fitness plan data."""

from typing import Any, Dict, Optional


class PlansTextReprBuilder:
    """Builds human-readable text representations for plan embedding."""

    @staticmethod
    def build_diet_plan(data: Dict[str, Any]) -> str:
        start = data.get("start_date", "unknown")
        end = data.get("end_date") or "ongoing"
        status = data.get("status", "ACTIVE")
        reason = data.get("plan_reason")

        parts = [f"Diet plan from {start} to {end} ({status})."]

        # Daily macro targets
        macros = []
        if data.get("calories"):
            macros.append(f"{data['calories']:.0f} cal")
        if data.get("protein"):
            macros.append(f"{data['protein']:.0f}g protein")
        if data.get("carbs"):
            macros.append(f"{data['carbs']:.0f}g carbs")
        if data.get("fats"):
            macros.append(f"{data['fats']:.0f}g fats")
        if data.get("fiber"):
            macros.append(f"{data['fiber']:.0f}g fiber")
        if macros:
            parts.append(f"Daily targets: {', '.join(macros)}.")

        # JSONB content
        content = data.get("content") or {}

        # Meal slots
        meals = content.get("meals", [])
        if meals:
            meal_parts = []
            for m in meals:
                slot = m.get("slot", "meal")
                time = m.get("time")
                cal = m.get("calories")
                prot = m.get("protein")
                carbs = m.get("carbs")
                fats = m.get("fats")
                suggestions = m.get("suggestions", [])

                desc = slot.capitalize()
                if time:
                    desc += f" at {time}"
                details = []
                if cal:
                    details.append(f"{cal:.0f} cal")
                if prot:
                    details.append(f"{prot:.0f}g protein")
                if carbs:
                    details.append(f"{carbs:.0f}g carbs")
                if fats:
                    details.append(f"{fats:.0f}g fats")
                if details:
                    desc += f" ({', '.join(details)})"
                if suggestions:
                    desc += f" — suggestions: {', '.join(suggestions[:3])}"
                meal_parts.append(desc)
            parts.append(f"Meals: {'; '.join(meal_parts)}.")

        # Restrictions
        restrictions = content.get("restrictions", [])
        if restrictions:
            parts.append(f"Dietary restrictions: {', '.join(restrictions)}.")

        # Hydration
        hydration = content.get("hydration_goal_oz")
        if hydration:
            parts.append(f"Hydration goal: {hydration:.0f} oz/day.")

        # Micronutrients
        micros = content.get("micronutrients") or {}
        micro_parts = []
        for key in ("calcium", "iron", "zinc", "magnesium"):
            val = micros.get(key)
            if val:
                micro_parts.append(f"{key} {val:.0f}mg")
        if micro_parts:
            parts.append(f"Micronutrients: {', '.join(micro_parts)}.")

        # Notes
        notes = content.get("notes")
        if notes:
            parts.append(f"Notes: {notes}")

        if reason:
            parts.append(f"Reason: {reason}.")

        return " ".join(parts)

    @staticmethod
    def build_fitness_plan(data: Dict[str, Any]) -> str:
        start = data.get("start_date", "unknown")
        end = data.get("end_date") or "ongoing"
        status = data.get("status", "ACTIVE")
        reason = data.get("plan_reason")
        steps = data.get("steps_goal")

        parts = [f"Fitness plan from {start} to {end} ({status})."]

        if steps:
            parts.append(f"Steps goal: {steps:.0f}/day.")

        # JSONB content
        content = data.get("content") or {}

        weekly_active = content.get("weekly_active_minutes")
        sessions_per_week = content.get("sessions_per_week")

        if weekly_active:
            parts.append(f"Weekly active minutes target: {weekly_active:.0f}.")
        if sessions_per_week:
            parts.append(f"Sessions per week: {sessions_per_week}.")

        # Weekly sessions
        sessions = content.get("weekly_sessions", [])
        if sessions:
            session_parts = []
            for s in sessions:
                day = s.get("day", "").capitalize()
                stype = s.get("type", "workout")
                dur = s.get("duration_min")
                exercises = s.get("exercises", [])

                desc = f"{day}: {stype}"
                if dur:
                    desc += f" ({dur:.0f} min)"
                if exercises:
                    ex_names = [e.get("name", "") for e in exercises[:4]]
                    desc += f" — {', '.join(ex_names)}"
                session_parts.append(desc)
            parts.append(f"Weekly schedule: {'; '.join(session_parts)}.")

        # Rest days
        rest_days = content.get("rest_days", [])
        if rest_days:
            parts.append(f"Rest days: {', '.join(d.capitalize() for d in rest_days)}.")

        # Notes
        notes = content.get("notes")
        if notes:
            parts.append(f"Notes: {notes}")

        if reason:
            parts.append(f"Reason: {reason}.")

        return " ".join(parts)
