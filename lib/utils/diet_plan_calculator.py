from datetime import date
from typing import Dict


class DietPlanCalculator:
    def __init__(
        self,
        weight: float,
        height: float,
        age: int,
        gender: str,
        activity_level: str,
    ):
        self.weight = weight
        self.height = height
        self.age = age
        self.gender = gender.lower()
        self.activity_level = activity_level.lower()

    def calculate_bmr(self) -> float:
        """Calculate BMR based on gender."""
        if self.gender == "male":
            return 10 * self.weight + 6.25 * self.height - 5 * self.age + 5
        else:
            return 10 * self.weight + 6.25 * self.height - 5 * self.age - 161

    def calculate_tdee(self) -> float:
        """Calculate TDEE based on BMR and activity level."""
        activity_multiplier = {
            "sedentary": 1.2,
            "lightly_active": 1.375,
            "moderately_active": 1.55,
            "very_active": 1.725,
            "super_active": 1.9,
        }.get(self.activity_level, 1.2)
        return self.calculate_bmr() * activity_multiplier

    def calculate_macronutrients(self, tdee: float) -> Dict[str, float]:
        """Calculate macronutrient distribution."""
        protein = self.weight * 1.8
        fats = tdee * 0.25 / 9
        carbs = (tdee - (protein * 4 + fats * 9)) / 4
        return {"protein": protein, "fats": fats, "carbs": carbs}

    def get_micronutrient_recommendations(self) -> Dict[str, float]:
        """Return micronutrient recommendations based on age and gender."""
        if self.gender == "male":
            if self.age < 18:
                return {
                    "calcium": 1300,
                    "iron": 11,
                    "zinc": 11,
                    "magnesium": 410,
                    "fiber": 25,
                }
            elif 18 <= self.age <= 50:
                return {
                    "calcium": 1000,
                    "iron": 8,
                    "zinc": 11,
                    "magnesium": 400,
                    "fiber": 30,
                }
            else:
                return {
                    "calcium": 1200,
                    "iron": 8,
                    "zinc": 11,
                    "magnesium": 420,
                    "fiber": 30,
                }
        else:
            if self.age < 18:
                return {
                    "calcium": 1300,
                    "iron": 15,
                    "zinc": 9,
                    "magnesium": 360,
                    "fiber": 25,
                }
            elif 18 <= self.age <= 50:
                return {
                    "calcium": 1000,
                    "iron": 18,
                    "zinc": 8,
                    "magnesium": 310,
                    "fiber": 25,
                }
            else:
                return {
                    "calcium": 1200,
                    "iron": 8,
                    "zinc": 8,
                    "magnesium": 320,
                    "fiber": 30,
                }
