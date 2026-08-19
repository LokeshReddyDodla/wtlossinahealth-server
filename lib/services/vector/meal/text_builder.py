"""Text representation builder for meal data."""

from typing import Dict, List, Any


class MealTextReprBuilder:
    """Builder for creating text representations of meal data."""

    @staticmethod
    def build(meal: Dict[str, Any]) -> str:
        """
        Build text representation for a meal.

        Args:
            meal: Meal data dictionary

        Returns:
            Text representation string
        """
        macros = meal.get("total_macro_nutritional_value", {}) or {}
        micros = meal.get("total_micro_nutritional_value", {}) or {}
        items = meal.get("items", []) or []

        # 1️⃣ — Base info
        meal_name = (meal.get("name") or "").strip()
        meal_type = (meal.get("type") or "Meal").lower()
        meal_description = (meal.get("description") or "").strip()
        meal_tags = ", ".join(meal.get("tags", [])) if meal.get("tags") else ""
        meal_time = meal.get("time", "")
        meal_date = meal.get("date", "")

        text_parts = [f"{meal_name} ({meal_type}) meal."]

        if meal_description:
            text_parts.append(f"Description: {meal_description}")
        if meal_tags:
            text_parts.append(f"Tags: {meal_tags}")
        if meal_date or meal_time:
            text_parts.append(f"Eaten on {meal_date} at {meal_time}.")

        # 2️⃣ — Structured nutrition summary
        if macros or micros:
            nutrition_summary = []
            if macros:
                nutrition_summary.append(
                    "Macronutrients: "
                    + ", ".join(f"{k}: {v}" for k, v in macros.items())
                )
            if micros:
                nutrition_summary.append(
                    "Micronutrients: "
                    + ", ".join(f"{k}: {v}" for k, v in micros.items())
                )
            text_parts.append(" ".join(nutrition_summary))

        # 3️⃣ — Individual food items (concise facts)
        for item in items:
            name = (item.get("name") or "").strip()
            quantity = item.get("serving_quantity", "")
            unit = item.get("serving_unit", "")
            size = item.get("serving_size", "")
            macro_vals = item.get("macro_nutritional_values", {}) or {}
            micro_vals = item.get("micro_nutritional_values", {}) or {}

            segments = []
            if name:
                segments.append(name)
            if quantity or unit:
                segments.append(f"({quantity} {unit})")
            if size:
                segments.append(f"Serving size: {size}.")
            if macro_vals:
                segments.append(
                    "Macronutrients: "
                    + ", ".join(f"{k}: {v}" for k, v in macro_vals.items())
                    + "."
                )
            if micro_vals:
                segments.append(
                    "Micronutrients: "
                    + ", ".join(f"{k}: {v}" for k, v in micro_vals.items())
                    + "."
                )

            text_parts.append(" ".join(segments))

        # 4️⃣ — Compute derived nutritional profile
        derived_tags = MealTextReprBuilder._generate_health_profile(macros)
        if derived_tags:
            text_parts.append(
                f"Overall health profile: {', '.join(derived_tags)}."
            )

        # 5️⃣ — Add natural language summary for embeddings
        text_parts.append(
            MealTextReprBuilder._generate_summary_sentence(meal, derived_tags)
        )

        # Combine into final embedding text
        combined_text = " ".join(filter(None, text_parts))
        return combined_text

    @staticmethod
    def _generate_health_profile(macros: Dict[str, float]) -> List[str]:
        """
        Classify meal into simple qualitative nutrition tags based on thresholds.

        Args:
            macros: Macronutrient dictionary

        Returns:
            List of health profile tags
        """
        tags = []
        calories = macros.get("calories", 0) or 0
        protein = macros.get("proteins", 0) or 0
        carbs = macros.get("carbohydrates", 0) or 0
        fats = macros.get("fats", 0) or 0
        fiber = macros.get("fiber", 0) or 0

        if calories > 700:
            tags.append("high calorie")
        elif calories < 300:
            tags.append("low calorie")

        if protein > 25:
            tags.append("high protein")
        elif protein < 10:
            tags.append("low protein")

        if carbs > 80:
            tags.append("high carb")
        elif carbs < 30:
            tags.append("low carb")

        if fats > 25:
            tags.append("high fat")
        elif fats < 10:
            tags.append("low fat")

        if fiber > 8:
            tags.append("high fiber")

        return tags

    @staticmethod
    def _generate_summary_sentence(
        meal: Dict[str, Any], tags: List[str]
    ) -> str:
        """
        Generate natural language summary sentence.

        Args:
            meal: Meal data dictionary
            tags: Health profile tags

        Returns:
            Summary sentence string
        """
        meal_type = (meal.get("type") or "meal").lower()
        meal_name = meal.get("name", "")
        if tags:
            summary = f"This {meal_type} ({meal_name}) is {', '.join(tags)}."
        else:
            summary = f"This {meal_type} ({meal_name}) has balanced nutrition."
        return summary
