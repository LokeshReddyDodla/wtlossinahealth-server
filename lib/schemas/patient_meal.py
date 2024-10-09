from datetime import date as datetime_date
from datetime import datetime
from datetime import time as datetime_time
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, HttpUrl


class PatientMacroNutritionalValue(BaseModel):
    calories: float
    proteins: float
    carbohydrates: float
    fats: float
    fiber: float

    class Config:
        from_attributes = True


class PatientMicroNutritionalValue(BaseModel):
    calcium: float
    iron: float
    zinc: float
    magnesium: float

    class Config:
        from_attributes = True


class FoodItem(BaseModel):
    name: str
    coordinates: Optional[List[float]]
    serving_size: str
    serving_quantity: float
    serving_unit: str
    macro_nutritional_values: PatientMacroNutritionalValue
    micro_nutritional_values: PatientMicroNutritionalValue

    class Config:
        from_attributes = True


class PatientMeal(BaseModel):
    id: UUID
    name: Optional[str]
    type: str
    date: datetime_date
    time: datetime_time
    items: Optional[List[FoodItem]] = []
    total_macro_nutritional_value: Optional[PatientMacroNutritionalValue] = (
        None
    )
    total_micro_nutritional_value: Optional[PatientMicroNutritionalValue] = (
        None
    )
    image_url: Optional[HttpUrl]
    description: Optional[str]
    source: Optional[str]
    score: Optional[float]
    feedback: Optional[str] = None
    tags: Optional[List[str]] = []
    context_id: Optional[str]
    analyzed: bool
    analyzed_at: Optional[datetime]
    uploaded_at: datetime
    patient_id: UUID

    class Config:
        from_attributes = True
