from typing import Any, Dict


class PatientProfileTextReprBuilder:
    @staticmethod
    def build(profile: Dict[str, Any]) -> str:
        first_name = profile.get("first_name", "")
        last_name = profile.get("last_name", "")
        name = f"{first_name} {last_name}".strip()
        age = profile.get("age", "unknown age")
        gender = profile.get("gender", "unspecified")
        height = profile.get("height", "unknown height")
        weight = profile.get("weight", "unknown weight")
        waist = profile.get("waist", "unknown waist")
        bmi = (
            round(weight / (height / 100) ** 2, 1)
            if height and weight
            else "unknown BMI"
        )

        activity_level = profile.get("daily_activity", {}).get(
            "activity_level", "unspecified"
        )

        # Allergies
        food_allergies = [
            a.get("allergy_name") for a in profile.get("food_allergies", [])
        ]
        drug_allergies = [
            a.get("allergy_name") for a in profile.get("drug_allergies", [])
        ]

        # Alcohol & Smoking
        alcohol = profile.get("alcohol_consumption", {})
        alcohol_consume = alcohol.get("consume_alcohol", False)
        alcohol_types = alcohol.get("type_of_alcohol", [])

        smoking = profile.get("smoking_habit", {})
        smoking_habit = smoking.get("smoke_status", False)
        years_of_smoking = smoking.get("years_of_smoking", 0)
        cigarettes_per_day = smoking.get("cigarettes_per_day", 0)

        # Diet & Eating
        eating = profile.get("eating_habit", {})
        diet_pref = eating.get("diet_preferences", {}).get(
            "preference", "unspecified"
        )
        cuisine_pref = eating.get("cuisine_preferences", [])
        meals_per_day = eating.get("meals_per_day", 0)
        snacks_count = eating.get("snacks_count", 0)
        meal_timings = [
            m.get("meal_type") for m in eating.get("meal_timings", [])
        ]

        # Sleep
        sleep = profile.get("sleep_habit", {})
        sleep_quality = sleep.get("sleep_quality", "unspecified")
        wake_up_fresh = sleep.get("wake_up_fresh", False)
        drowsy_day = sleep.get("drowsy_day", False)

        # Diabetes
        diabetic = profile.get("diabetic_history", {})
        diabetes_type = diabetic.get("type_of_diabetes", "unspecified")
        years_with_diabetes = diabetic.get("years_with_diabetes", 0)
        is_pregnant = diabetic.get("is_pregnant", False)

        # Family & Medical
        family_histories = profile.get("family_diabetic_histories", [])
        family_info = ", ".join(
            f"{f.get('family_member')} ({f.get('years_with_diabetes', '?')} yrs)"
            for f in family_histories
        )

        medical_histories = profile.get("medical_histories", [])
        medical_info = ", ".join(
            f"{m.get('condition')} ({m.get('duration_years', '?')} yrs)"
            for m in medical_histories
        )

        # Build text representation
        parts = [
            f"name: {name}",
            f"age: {age}",
            f"gender: {gender}",
            f"height_cm: {height}",
            f"weight_kg: {weight}",
            f"waist_cm: {waist}",
            f"bmi: {bmi}",
            f"activity_level: {activity_level}",
            f"diet_preference: {diet_pref}",
            f"cuisines: {', '.join(cuisine_pref)}",
            f"meals_per_day: {meals_per_day}",
            f"snacks_count: {snacks_count}",
            f"meal_timings: {', '.join(meal_timings)}",
            f"food_allergies: {', '.join(food_allergies)}",
            f"drug_allergies: {', '.join(drug_allergies)}",
            f"alcohol_consumption: {alcohol_consume}",
            f"alcohol_types: {', '.join(alcohol_types)}",
            f"smoking_habit: {smoking_habit}",
            f"years_of_smoking: {years_of_smoking}",
            f"cigarettes_per_day: {cigarettes_per_day}",
            f"wake_up_fresh: {wake_up_fresh}",
            f"drowsy_day: {drowsy_day}",
            f"sleep_quality: {sleep_quality}",
            f"diabetes_type: {diabetes_type}",
            f"years_with_diabetes: {years_with_diabetes}",
            f"is_pregnant: {is_pregnant}",
            f"family_history: {family_info}",
            f"medical_history: {medical_info}",
        ]

        return " | ".join(parts)
