from datetime import datetime
from typing import Optional

from pydantic import BaseModel, HttpUrl
from typing import List, Optional

from uuid import UUID


class PatientMacroNutritionalValue(BaseModel):
    calories: float
    proteins: float
    carbohydrates: float
    fats: float
    fiber: float

    class Config:
        orm_mode = True


class PatientMicroNutritionalValue(BaseModel):
    calcium: float
    iron: float
    zinc: float
    magnesium: float
    cholesterol: float

    class Config:
        orm_mode = True


class FoodItem(BaseModel):
    name: str
    coordinates: Optional[List[float]]
    serving_size: str
    serving_quantity: float
    serving_unit: str
    macro_nutritional_values: PatientMacroNutritionalValue
    micro_nutritional_values: PatientMicroNutritionalValue

    class Config:
        orm_mode = True


class PatientMeal(BaseModel):
    id: UUID
    name: Optional[str]
    type: str
    time: datetime
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
        orm_mode = True
