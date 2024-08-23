from datetime import datetime
from typing import Optional

from pydantic import BaseModel
from typing import List, Optional

from uuid import UUID


class MacroNutritionalValues(BaseModel):
    calories: str
    proteins: str
    carbohydrates: str
    fats: str
    fiber: str

    class Config:
        orm_mode = True


class MicroNutritionalValues(BaseModel):
    calcium: str
    iron: str
    zinc: str
    magnesium: str
    cholesterol: str

    class Config:
        orm_mode = True


class FoodItem(BaseModel):
    name: str
    coordinates: Optional[List[float]]
    serving_size: str
    serving_quantity: str
    serving_unit: str
    macro_nutritional_values: MacroNutritionalValues
    micro_nutritional_values: MicroNutritionalValues

    class Config:
        orm_mode = True


class TotalMacroNutritionalValue(BaseModel):
    calories: str
    proteins: str
    carbohydrates: str
    fats: str
    fiber: str

    class Config:
        orm_mode = True


class TotalMicroNutritionalValue(BaseModel):
    calcium: str
    iron: str
    zinc: str
    magnesium: str
    cholesterol: str

    class Config:
        orm_mode = True


class MealResponse(BaseModel):
    id: UUID
    type: str
    time: datetime
    items: Optional[List[FoodItem]] = []
    total_macro_nutritional_value: Optional[TotalMacroNutritionalValue] = None
    total_micro_nutritional_value: Optional[TotalMicroNutritionalValue] = None
    image_url: Optional[str]
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

    @classmethod
    def from_orm(cls, obj):
        kwargs = {}
        state = (
            obj._sa_instance_state
        )  # Access the internal state of the SQLAlchemy instance

        for name, field in cls.__fields__.items():
            if name in state.dict:  # Check if the attribute is already loaded
                kwargs[name] = getattr(obj, name)
            elif (
                name not in state.unloaded
            ):  # Ensure it's not an unloaded attribute
                kwargs[name] = getattr(obj, name)

        return cls(**kwargs)


class MealDescription(BaseModel):  # TODO: remove this
    type: str
    items: List[FoodItem]
    total_macro_nutritional_value: TotalMacroNutritionalValue
    total_micro_nutritional_value: TotalMicroNutritionalValue
    image_url: str
    description: Optional[str] = None
    feedback: str
    tags: List[str]
    context_id: str
