from typing import Optional

from pydantic import Field
from pydantic import BaseModel
from typing import List, Dict, Optional, Union

from rest_server.response_models import SuccessResponse


class NutritionalValues(BaseModel):
    calories: str
    proteins: str
    carbohydrates: str
    fats: str
    fiber: str


class FoodItem(BaseModel):
    name: str
    coordinates: List
    serving_size: str
    serving_quantity: str
    serving_unit: str
    nutritional_values: NutritionalValues

class TotalNutritionalValue(BaseModel):
    calories: str
    proteins: str
    carbohydrates: str
    fats: str
    fiber: str

class FoodDescription(BaseModel):
    meal_type: str
    items: List[FoodItem]
    total_nutritional_value: TotalNutritionalValue
    image_url: str
    description: Optional[str] = None
    feedback: str


class MealAnalysisResponse(SuccessResponse):
    data: FoodDescription

