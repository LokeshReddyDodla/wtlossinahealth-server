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
    serving_size: str
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



class CreateUser(BaseModel):
    """
    JSON Schema for creating a user
    """

    manager_name: str = Field(description="Team manager name", min_length=3)
    team_name: str = Field(description="Team name", min_length=3)


class User(BaseModel):
    """
    JSON Schema for fetching User
    """

    signup_complete: bool = Field(
        description="Whether signup is complete",
        default=False,
    )
    user_id: Optional[str] = Field(description="User ID")
    manager_name: Optional[str] = Field(description="Team manager name")
    team_name: Optional[str] = Field(description="Team name")
    ens_address: Optional[str] = Field(description="ENS address of the team")
