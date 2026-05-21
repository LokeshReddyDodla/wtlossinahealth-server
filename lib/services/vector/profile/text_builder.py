"""Text representation builder for patient profile data.

Builds the prose representation of a patient that gets embedded into Qdrant
and fed into LLM prompts. Reads the clean v1 fields first, falls back to
legacy fields during the soak window (until Deploy 2 drops legacy columns).
"""

from typing import Any, Dict, List


class PatientProfileTextReprBuilder:
    """Builder for creating text representations of patient profiles."""

    @staticmethod
    def build(profile: Dict[str, Any]) -> str:
        profile = profile or {}

        def sd(value):
            return value if isinstance(value, dict) else {}

        def sl(value):
            if isinstance(value, list):
                return value
            if isinstance(value, str):
                return [value]
            if value is None:
                return []
            try:
                return list(value)
            except Exception:
                return []

        def prefer(*candidates):
            """Return the first non-None, non-empty-string candidate."""
            for c in candidates:
                if c is not None and c != "":
                    return c
            return None

        # ─── Identity & body ───────────────────────────────────────────────
        first_name = profile.get("first_name", "")
        last_name = profile.get("last_name", "")
        name = f"{first_name} {last_name}".strip()
        age = profile.get("age", "unknown")
        gender = profile.get("gender", "unspecified")
        occupation = profile.get("occupation")

        height = prefer(profile.get("height_cm"), profile.get("height"))
        weight = prefer(profile.get("weight_kg"), profile.get("weight"))
        waist = prefer(profile.get("waist_cm"), profile.get("waist"))
        hip = profile.get("hip_cm")
        bmi = (
            round(weight / (height / 100) ** 2, 1)
            if height and weight
            else "unknown"
        )

        # ─── Activity ──────────────────────────────────────────────────────
        daily_activity = sd(profile.get("daily_activity"))
        activity_level = daily_activity.get("activity_level", "unspecified")

        # ─── Allergies (new: name+severity+other; fallback to allergy_name) ─
        def fmt_allergy(a: dict, reaction_key: str = None) -> str:
            name_val = prefer(a.get("name"), a.get("allergy_name")) or ""
            label = name_val
            if name_val == "OTHER" and a.get("name_other"):
                label = f"OTHER ({a['name_other']})"
            extras: List[str] = []
            if a.get("severity"):
                extras.append(f"severity={a['severity']}")
            if reaction_key and a.get(reaction_key):
                extras.append(f"reaction={a[reaction_key]}")
            return f"{label} [{', '.join(extras)}]" if extras else label

        food_allergies = [
            fmt_allergy(a)
            for a in sl(profile.get("food_allergies"))
            if isinstance(a, dict)
        ]
        drug_allergies = [
            fmt_allergy(a, reaction_key="reaction")
            for a in sl(profile.get("drug_allergies"))
            if isinstance(a, dict)
        ]

        # ─── Alcohol (new: status enum + drinks_per_session) ──────────────
        alcohol = sd(profile.get("alcohol_consumption"))
        alcohol_status = prefer(
            alcohol.get("status"),
            # legacy bool → coarse enum mapping
            ("REGULAR" if alcohol.get("consume_alcohol") else "NEVER")
            if alcohol.get("consume_alcohol") is not None
            else None,
        ) or "unspecified"
        alcohol_frequency = alcohol.get("frequency") or "unspecified"
        drinks_per_session = prefer(
            alcohol.get("drinks_per_session"), alcohol.get("quantity")
        )
        alcohol_types = sl(alcohol.get("type_of_alcohol"))
        alcohol_quit_years_ago = alcohol.get("quit_years_ago")

        # ─── Smoking (new: status enum + smoke_type list) ──────────────────
        smoking = sd(profile.get("smoking_habit"))
        smoking_status = prefer(
            smoking.get("status"),
            ("CURRENT" if smoking.get("smoke_status") else "NEVER")
            if smoking.get("smoke_status") is not None
            else None,
        ) or "unspecified"
        smoke_types = sl(smoking.get("smoke_type"))
        years_of_smoking = smoking.get("years_of_smoking")
        cigarettes_per_day = smoking.get("cigarettes_per_day")
        smoking_quit_years_ago = smoking.get("quit_years_ago")

        # ─── Eating (new: dietary_preferences[] + detail) ──────────────────
        eating = sd(profile.get("eating_habit"))
        meals_per_day = eating.get("meals_per_day")
        snacks_count = eating.get("snacks_count")

        dietary_preferences = sl(eating.get("dietary_preferences"))
        if not dietary_preferences:
            # Legacy: single PatientDietPreference object {preference, detail}
            legacy = eating.get("diet_preferences")
            if isinstance(legacy, dict) and legacy.get("preference"):
                dietary_preferences = [legacy["preference"]]
        diet_pref_detail = prefer(
            eating.get("diet_preferences_detail"),
            (eating.get("diet_preferences") or {}).get("detail")
            if isinstance(eating.get("diet_preferences"), dict)
            else None,
        )
        cuisine_pref = sl(eating.get("cuisine_preferences"))
        meal_timings = [
            f"{m.get('meal_type')}@{m.get('time')}"
            for m in sl(eating.get("meal_timings"))
            if isinstance(m, dict)
        ]

        # ─── Sleep (new: average_sleep_hours float + snores) ──────────────
        sleep = sd(profile.get("sleep_habit"))
        sleep_quality = sleep.get("sleep_quality", "unspecified")
        average_sleep_hours = prefer(
            sleep.get("average_sleep_hours"),
            sleep.get("average_sleep_duration"),
        )
        wake_up_fresh = sleep.get("wake_up_fresh")
        drowsy_day = sleep.get("drowsy_day")
        snores = sleep.get("snores")

        # ─── Diabetes (new: diagnosed_at) ─────────────────────────────────
        diabetic = sd(profile.get("diabetic_history"))
        diabetes_type = diabetic.get("type_of_diabetes", "unspecified")
        years_with_diabetes = diabetic.get("years_with_diabetes")
        diagnosed_at = diabetic.get("diagnosed_at")

        # ─── Family history (new: type_of_diabetes per relative) ──────────
        family_info = ", ".join(
            f"{f.get('family_member')}"
            f"{(' ' + f.get('type_of_diabetes')) if f.get('type_of_diabetes') else ''}"
            f" ({f.get('years_with_diabetes', '?')} yrs)"
            for f in sl(profile.get("family_diabetic_histories"))
            if isinstance(f, dict)
        )

        # ─── Medical (new: condition_other, status, started_at) ───────────
        def fmt_medical(m: dict) -> str:
            cond = m.get("condition") or ""
            if cond == "OTHER" and m.get("condition_other"):
                cond = f"OTHER ({m['condition_other']})"
            extras: List[str] = []
            if m.get("status"):
                extras.append(m["status"])
            duration = m.get("duration_years")
            if duration:
                extras.append(f"{duration} yrs")
            if m.get("started_at"):
                extras.append(f"since {m['started_at']}")
            details = m.get("details")
            base = f"{cond} [{', '.join(extras)}]" if extras else cond
            return f"{base}: {details}" if details else base

        medical_info = ", ".join(
            fmt_medical(m)
            for m in sl(profile.get("medical_histories"))
            if isinstance(m, dict)
        )

        # ─── Reproductive health (only if any data present) ───────────────
        repro = sd(profile.get("reproductive_health"))
        if not repro:
            # Legacy: pregnancy lived on diabetic_history
            if diabetic.get("is_pregnant") is not None or diabetic.get("pregnancy_weeks"):
                repro = {
                    "is_pregnant": diabetic.get("is_pregnant"),
                    "pregnancy_weeks": diabetic.get("pregnancy_weeks"),
                }

        # ─── Build the final text ─────────────────────────────────────────
        parts = [
            f"name: {name}",
            f"age: {age}",
            f"gender: {gender}",
            f"occupation: {occupation}" if occupation else None,
            f"height_cm: {height or 'unknown'}",
            f"weight_kg: {weight or 'unknown'}",
            f"waist_cm: {waist or 'unknown'}",
            f"hip_cm: {hip}" if hip else None,
            f"bmi: {bmi}",
            f"activity_level: {activity_level}",
            f"diet_preferences: {', '.join(dietary_preferences) or 'unspecified'}",
            f"diet_preferences_detail: {diet_pref_detail}" if diet_pref_detail else None,
            f"cuisines: {', '.join(cuisine_pref)}",
            f"meals_per_day: {meals_per_day}" if meals_per_day else None,
            f"snacks_count: {snacks_count}" if snacks_count is not None else None,
            f"meal_timings: {', '.join(meal_timings)}" if meal_timings else None,
            f"food_allergies: {', '.join(food_allergies)}" if food_allergies else None,
            f"drug_allergies: {', '.join(drug_allergies)}" if drug_allergies else None,
            f"alcohol_status: {alcohol_status}",
            f"alcohol_frequency: {alcohol_frequency}",
            f"drinks_per_session: {drinks_per_session}" if drinks_per_session else None,
            f"alcohol_types: {', '.join(map(str, alcohol_types))}" if alcohol_types else None,
            f"alcohol_quit_years_ago: {alcohol_quit_years_ago}" if alcohol_quit_years_ago else None,
            f"smoking_status: {smoking_status}",
            f"smoke_type: {', '.join(map(str, smoke_types))}" if smoke_types else None,
            f"years_of_smoking: {years_of_smoking}" if years_of_smoking else None,
            f"cigarettes_per_day: {cigarettes_per_day}" if cigarettes_per_day else None,
            f"smoking_quit_years_ago: {smoking_quit_years_ago}" if smoking_quit_years_ago else None,
            f"sleep_quality: {sleep_quality}",
            f"average_sleep_hours: {average_sleep_hours}" if average_sleep_hours else None,
            f"wake_up_fresh: {wake_up_fresh}" if wake_up_fresh is not None else None,
            f"drowsy_day: {drowsy_day}" if drowsy_day is not None else None,
            f"snores: {snores}" if snores is not None else None,
            f"diabetes_type: {diabetes_type}",
            f"years_with_diabetes: {years_with_diabetes}" if years_with_diabetes else None,
            f"diabetes_diagnosed_at: {diagnosed_at}" if diagnosed_at else None,
            f"family_history: {family_info}" if family_info else None,
            f"medical_history: {medical_info}" if medical_info else None,
        ]

        if repro:
            if repro.get("is_pregnant"):
                parts.append(
                    f"pregnant: yes ({repro.get('pregnancy_weeks', '?')} weeks)"
                )
            if repro.get("menopause_status") and repro["menopause_status"] != "NOT_APPLICABLE":
                parts.append(f"menopause_status: {repro['menopause_status']}")
            if repro.get("period_regularity") and repro["period_regularity"] != "NOT_APPLICABLE":
                parts.append(f"period_regularity: {repro['period_regularity']}")
            if repro.get("uses_contraception") is not None:
                parts.append(f"uses_contraception: {repro['uses_contraception']}")

        return " | ".join(p for p in parts if p)
