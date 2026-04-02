from datetime import datetime, date as datetime_date
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# JSONB content models (validated by Pydantic, stored as JSONB in PostgreSQL)
# ---------------------------------------------------------------------------


class DietMealSlot(BaseModel):
    slot: str = Field(..., description="Meal slot: breakfast, lunch, dinner, snack, etc.")
    time: Optional[str] = Field(None, description="Suggested time in HH:MM format")
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fats: Optional[float] = None
    suggestions: list[str] = Field(default_factory=list, description="Food suggestions")


class DietMicronutrients(BaseModel):
    calcium: Optional[float] = None
    iron: Optional[float] = None
    zinc: Optional[float] = None
    magnesium: Optional[float] = None


class DietPlanContent(BaseModel):
    """Structured diet plan content stored as JSONB.

    Example payload::

        {
          "meals": [
            {
              "slot": "breakfast",
              "time": "08:00",
              "calories": 500,
              "protein": 30,
              "carbs": 60,
              "fats": 20,
              "suggestions": ["oatmeal with berries", "eggs and toast"]
            },
            {
              "slot": "lunch",
              "time": "13:00",
              "calories": 600,
              "protein": 40,
              "carbs": 50,
              "fats": 25,
              "suggestions": ["grilled chicken salad"]
            },
            {
              "slot": "dinner",
              "time": "19:00",
              "calories": 600,
              "protein": 35,
              "carbs": 50,
              "fats": 25,
              "suggestions": []
            },
            {
              "slot": "snack",
              "time": "16:00",
              "calories": 300,
              "protein": 15,
              "carbs": 30,
              "fats": 10,
              "suggestions": ["greek yogurt", "nuts"]
            }
          ],
          "restrictions": ["gluten-free"],
          "hydration_goal_oz": 80,
          "micronutrients": {
            "calcium": 1000,
            "iron": 18,
            "zinc": 11,
            "magnesium": 400
          },
          "notes": "Focus on protein-rich meals"
        }
    """
    meals: list[DietMealSlot] = Field(default_factory=list)
    restrictions: list[str] = Field(default_factory=list, description="e.g. gluten-free, dairy-free")
    hydration_goal_oz: Optional[float] = None
    micronutrients: Optional[DietMicronutrients] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Diet recommendation (macro summary used by meal analysis endpoints)
# ---------------------------------------------------------------------------


class DietRecommendation(BaseModel):
    """Flat macro targets used as meal recommendation context."""
    calories: float = 0
    protein: float = 0
    carbs: float = 0
    fats: float = 0
    fiber: float = 0


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class PatientDietPlanCreate(BaseModel):
    """Create a diet plan.

    Full request example::

        {
          "calories": 2000,
          "protein": 120,
          "carbs": 200,
          "fats": 70,
          "fiber": 30,
          "start_date": "2026-04-03",
          "end_date": "2026-06-30",
          "is_default": false,
          "status": "ACTIVE",
          "plan_reason": "Weight loss program",
          "content": {
            "meals": [
              {
                "slot": "breakfast",
                "time": "08:00",
                "calories": 500,
                "protein": 30,
                "carbs": 60,
                "fats": 20,
                "suggestions": ["oatmeal with berries", "eggs and toast"]
              },
              {
                "slot": "lunch",
                "time": "13:00",
                "calories": 600,
                "protein": 40,
                "carbs": 50,
                "fats": 25,
                "suggestions": ["grilled chicken salad"]
              },
              {
                "slot": "dinner",
                "time": "19:00",
                "calories": 600,
                "protein": 35,
                "carbs": 50,
                "fats": 25,
                "suggestions": []
              },
              {
                "slot": "snack",
                "time": "16:00",
                "calories": 300,
                "protein": 15,
                "carbs": 30,
                "fats": 10,
                "suggestions": ["greek yogurt", "nuts"]
              }
            ],
            "restrictions": ["gluten-free"],
            "hydration_goal_oz": 80,
            "micronutrients": {"calcium": 1000, "iron": 18, "zinc": 11, "magnesium": 400},
            "notes": "Focus on protein-rich meals"
          }
        }
    """
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fats: Optional[float] = None
    fiber: Optional[float] = None
    content: Optional[DietPlanContent] = None
    start_date: datetime_date
    end_date: Optional[datetime_date] = None
    is_default: bool = False
    status: str = "ACTIVE"
    plan_reason: Optional[str] = None


class PatientDietPlanUpdate(BaseModel):
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fats: Optional[float] = None
    fiber: Optional[float] = None
    content: Optional[DietPlanContent] = None
    start_date: Optional[datetime_date] = None
    end_date: Optional[datetime_date] = None
    is_default: Optional[bool] = None
    status: Optional[str] = None
    plan_reason: Optional[str] = None


class PatientDietPlan(BaseModel):
    diet_plan_id: UUID
    patient_id: UUID
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fats: Optional[float] = None
    fiber: Optional[float] = None
    content: Optional[DietPlanContent] = None
    start_date: datetime_date
    end_date: Optional[datetime_date] = None
    is_default: bool = False
    status: str = "ACTIVE"
    plan_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
