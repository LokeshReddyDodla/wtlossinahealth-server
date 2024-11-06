from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, HttpUrl, constr

from lib.schemas.meal_stats import DailyMealStats
from lib.schemas.patient_diet_plan import MealDistribution
from lib.schemas.patient_meal import PatientMeal
from rest_server.response_models import SuccessResponse

PatientMealsResponse = SuccessResponse[List[PatientMeal]]

PatientMealStatsResponse = SuccessResponse[DailyMealStats]


class PatientMealUploadRequest(BaseModel):
    type: str
    datetime: datetime
    source: Optional[str] = "app"
    description: Optional[str] = None
    image_url: HttpUrl


class PatientMealAnalysis(BaseModel):
    meal_data: PatientMeal
    meal_recommendation: MealDistribution


PatientMealAnalysisResponse = SuccessResponse[PatientMealAnalysis]

PatientMealUploadResponse = SuccessResponse[PatientMeal]
