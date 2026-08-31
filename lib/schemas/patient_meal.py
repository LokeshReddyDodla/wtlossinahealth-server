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
    center_point: Optional[List[float]] = Field(
        default=None,
        description="Center point [x, y] of the food item in the image, normalized 0-1000.",
    )
    serving_size: str = Field(
        description="Serving size description (e.g., 'medium')"
    )
    serving_quantity: float = Field(description="Quantity of the serving")
    serving_unit: str = Field(
        description="Unit of the serving (e.g., 'cup', 'grams')"
    )
    macro_nutritional_values: PatientMacroNutritionalValue
    micro_nutritional_values: PatientMicroNutritionalValue

    class Config:
        from_attributes = True


class PatientMeal(BaseModel):
    id: UUID
    name: Optional[str]
    type: str
    slot: Optional[str] = None
    date: datetime_date
    time: datetime_time
    items: Optional[List[PatientFoodItem]] = []
    total_macro_nutritional_value: Optional[PatientMacroNutritionalValue] = (
        None
    )
    total_micro_nutritional_value: Optional[PatientMicroNutritionalValue] = (
        None
    )
    image_urls: Optional[List[HttpUrl]] = None
    audio_url: Optional[HttpUrl] = None
    description: Optional[str]
    source: Optional[str]
    score: Optional[float]
    tags: Optional[List[str]] = []
    analyzed: bool
    analyzed_at: Optional[datetime]
    uploaded_at: datetime
    patient_id: UUID

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

        # image_urls is the source of truth; derive both directions for compat
        urls = kwargs.get("image_urls")
        if urls:
            kwargs["image_url"] = urls[0]
        elif kwargs.get("image_url"):
            kwargs["image_urls"] = [kwargs["image_url"]]

        return cls(**kwargs)
