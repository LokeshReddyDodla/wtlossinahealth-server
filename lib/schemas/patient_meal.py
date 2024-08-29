from datetime import datetime
from typing import Optional

from pydantic import BaseModel
from typing import List, Optional

from uuid import UUID


class PatientMacroNutritionalValue(BaseModel):
    calories: str
    proteins: str
    carbohydrates: str
    fats: str
    fiber: str

    class Config:
        orm_mode = True


class PatientMicroNutritionalValue(BaseModel):
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
    macro_nutritional_values: PatientMacroNutritionalValue
    micro_nutritional_values: PatientMicroNutritionalValue

    class Config:
        orm_mode = True


class PatientTotalMacroNutritionalValue(BaseModel):
    calories: str
    proteins: str
    carbohydrates: str
    fats: str
    fiber: str

    class Config:
        orm_mode = True


class PatientTotalMicroNutritionalValue(BaseModel):
    calcium: str
    iron: str
    zinc: str
    magnesium: str
    cholesterol: str

    class Config:
        orm_mode = True


class PatientMeal(BaseModel):
    id: UUID
    name: Optional[str]
    type: str
    time: datetime
    items: Optional[List[FoodItem]] = []
    total_macro_nutritional_value: Optional[
        PatientTotalMacroNutritionalValue
    ] = None
    total_micro_nutritional_value: Optional[
        PatientTotalMicroNutritionalValue
    ] = None
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


class PatientMealResponse(PatientMeal):
    @classmethod
    def from_orm(cls, obj):
        state = obj._sa_instance_state

        kwargs = {
            name: getattr(obj, name)
            for name in cls.__fields__
            if name in state.dict or name not in state.unloaded
        }

        return cls(**kwargs)


class MealDescription(BaseModel):  # TODO: remove this
    type: str
    items: List[FoodItem]
    total_macro_nutritional_value: PatientTotalMacroNutritionalValue
    total_micro_nutritional_value: PatientTotalMicroNutritionalValue
    image_url: str
    description: Optional[str] = None
    feedback: str
    tags: List[str]
    context_id: str
