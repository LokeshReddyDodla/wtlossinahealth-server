from datetime import datetime
from typing import Optional

from pydantic import BaseModel, HttpUrl

from lib.schemas.patient_diet_plan import DietRecommendation
from lib.schemas.patient_meal import PatientMeal


class PatientMealUpdateRequest(BaseModel):
    type: str
    datetime: datetime
    source: Optional[str] = "app"
    description: Optional[str] = None
    image_url: Optional[HttpUrl] = None
    image_urls: Optional[list[HttpUrl]] = None


class PatientMealAnalysis(BaseModel):
    meal_data: PatientMeal
    meal_recommendation: DietRecommendation
