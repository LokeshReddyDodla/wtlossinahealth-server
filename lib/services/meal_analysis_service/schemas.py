from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TokenUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int
    input_token_details: Optional[Dict[str, int]] = None
    output_token_details: Optional[Dict[str, int]] = None


class MacroNutritionalValue(BaseModel):
    calories: float = Field(description="Total calories")
    proteins: float = Field(description="Total proteins")
    carbohydrates: float = Field(description="Total carbohydrates")
    fats: float = Field(description="Total fats")
    fiber: float = Field(description="Total fiber")

    class Config:
        from_attributes = True


class MicroNutritionalValue(BaseModel):
    calcium: float = Field(description="Calcium in mg")
    iron: float = Field(description="Iron in mg")
    zinc: float = Field(description="Zinc in mg")
    magnesium: float = Field(description="Magnesium in mg")

    class Config:
        from_attributes = True


class FoodItem(BaseModel):
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
    macro_nutritional_values: MacroNutritionalValue
    micro_nutritional_values: MicroNutritionalValue

    class Config:
        from_attributes = True


class MealAnalysisRequest(BaseModel):
    context: Dict[
        str, Any
    ]  # Generic context for analysis (e.g., user profile, preferences)
    meal_time: str
    meal_type: str
    image_url: Optional[str] = None
    meal_description: Optional[str] = None
    update_fields: Optional[Dict[str, Any]] = None


class MealAnalysisResponse(BaseModel):
    meal_name: str = Field(description="Name of the meal")
    meal_type: str = Field(description="Type of the meal")
    items: List[FoodItem] = Field(
        description="List of food items identified in the meal"
    )
    total_macro_nutritional_value: MacroNutritionalValue
    total_micro_nutritional_value: MicroNutritionalValue
    feedback: str = Field(
        description="Personalized feedback based on the analysis"
    )
    tags: List[str] = Field(description="Tags like GI levels")
    score: float = Field(description="Overall meal score out of 10")


class MealAnalysisResult(BaseModel):
    meal_information: MealAnalysisResponse
    token_usage: TokenUsage
