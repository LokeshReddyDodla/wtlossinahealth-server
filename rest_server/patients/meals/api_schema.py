from datetime import datetime
from typing import Optional

from pydantic import BaseModel, HttpUrl

from lib.schemas.patient_diet_plan import MealDistribution
from lib.schemas.patient_meal import PatientMeal


class PatientMealUploadRequest(BaseModel):
    type: str
    datetime: datetime
    source: Optional[str] = "app"
    description: Optional[str] = None
    image_url: Optional[HttpUrl] = None


class PatientMealAnalysis(BaseModel):
    meal_data: PatientMeal
    meal_recommendation: MealDistribution
