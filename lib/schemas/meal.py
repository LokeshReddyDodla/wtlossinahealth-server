from datetime import datetime
from typing import Optional

from pydantic import BaseModel
from typing import List, Optional

from uuid import UUID


class NutritionalValues(BaseModel):
    calories: str
    proteins: str
    carbohydrates: str
    fats: str
    fiber: str

    class Config:
        orm_mode = True


class FoodItem(BaseModel):
    name: str
    coordinates: Optional[List[float]]
    serving_size: str
    serving_quantity: str
    serving_unit: str
    nutritional_values: NutritionalValues

    class Config:
        orm_mode = True


class TotalNutritionalValue(BaseModel):
    calories: str
    proteins: str
    carbohydrates: str
    fats: str
    fiber: str

    class Config:
        orm_mode = True


class MealResponse(BaseModel):
    id: UUID
    type: str
    time: datetime
    items: Optional[List[FoodItem]] = []
    total_nutritional_value: Optional[TotalNutritionalValue] = None
    image_url: Optional[str]
    description: Optional[str]
    source: Optional[str]
    feedback: Optional[str] = None
    tags: Optional[List[str]] = []
    context_id: Optional[str]
    analyzed: bool
    uploaded_at: datetime
    user_id: UUID

    class Config:
        orm_mode = True


class MealDescription(BaseModel):
    type: str
    items: List[FoodItem]
    total_nutritional_value: TotalNutritionalValue
    image_url: str
    description: Optional[str] = None
    feedback: str
    tags: List[str]
    context_id: str
