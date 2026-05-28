from datetime import date as datetime_date
from datetime import datetime
from datetime import time as datetime_time
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class PatientMacroNutritionalValue(BaseModel):
    calories: float = Field(description="Total calories")
    proteins: float = Field(description="Total proteins")
    carbohydrates: float = Field(description="Total carbohydrates")
    simple_carbs: Optional[float] = Field(
        default=None,
        description="Simple carbohydrates subset of total carbohydrates",
    )
    complex_carbs: Optional[float] = Field(
        default=None,
        description="Complex carbohydrates subset of total carbohydrates",
    )
    fats: float = Field(description="Total fats")
    fiber: float = Field(description="Total fiber")

    class Config:
        from_attributes = True


class PatientMicroNutritionalValue(BaseModel):
    calcium: float = Field(description="Calcium in mg")
    iron: float = Field(description="Iron in mg")
    zinc: float = Field(description="Zinc in mg")
    magnesium: float = Field(description="Magnesium in mg")

    class Config:
        from_attributes = True


class PatientFoodItem(BaseModel):
    name: str = Field(description="Name of the dish")
    coordinates: Optional[List[float]] = Field(
        description=(
            "Bounding box coordinates of the food item in the image, specified as "
            "[x_min, y_min, x_max, y_max]. These coordinates represent the exact region "
            "of the food item (e.g., the food itself rather than the plate or container)."
        )
    )
    serving_size: str = Field(
        description="Serving size description (e.g., 'medium')"
    )
    serving_quantity: float = Field(description="Quantity of the serving")
    serving_unit: str = Field(
        description="Unit of the serving (e.g., 'cup', 'grams')"
    )
    category: Optional[str] = Field(
        description="Category of the food item (e.g., 'solid', 'drink')"
    )
    macro_nutritional_values: PatientMacroNutritionalValue
    micro_nutritional_values: PatientMicroNutritionalValue

    class Config:
        from_attributes = True


class MealAnalysisResponse(BaseModel):
    meal_name: str = Field(description="Name of the meal")
    meal_type: str = Field(description="Type of the meal")
    items: List[PatientFoodItem] = Field(
        description="List of food items identified in the meal"
    )
    total_macro_nutritional_value: PatientMacroNutritionalValue
    total_micro_nutritional_value: PatientMicroNutritionalValue
    feedback: str = Field(
        description="Personalized feedback based on the analysis"
    )
    tags: List[str] = Field(description="Tags like GI levels")
    score: float = Field(description="Overall meal score out of 10")


class PatientMeal(BaseModel):
    id: UUID
    name: Optional[str]
    type: str
    date: datetime_date
    time: datetime_time
    items: Optional[List[PatientFoodItem]] = []
    total_macro_nutritional_value: Optional[PatientMacroNutritionalValue] = (
        None
    )
    total_micro_nutritional_value: Optional[PatientMicroNutritionalValue] = (
        None
    )
    image_url: Optional[HttpUrl]
    audio_url: Optional[HttpUrl] = None
    description: Optional[str]
    source: Optional[str]
    score: Optional[float]
    feedback: Optional[str] = None
    tags: Optional[List[str]] = []
    analyzed: bool
    analyzed_at: Optional[datetime]
    uploaded_at: datetime
    patient_id: UUID
    ai_insight: Optional[str] = None

    class Config:
        from_attributes = True

    @classmethod
    def from_orm(cls, obj):
        state = obj._sa_instance_state

        kwargs = {
            name: getattr(obj, name)
            for name in cls.model_fields
            if name in state.dict or name not in state.unloaded
        }

        return cls(**kwargs)
