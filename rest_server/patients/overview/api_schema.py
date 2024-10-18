from typing import Any, Optional

from pydantic import BaseModel

from lib.schemas.glucose_stats import GlucoseLevelStats
from lib.schemas.meal_stats import DailyMealStats
from rest_server.response_models import SuccessResponse


class PatientOverview(BaseModel):
    meal_stats: Optional[DailyMealStats] = None
    fitness_stats: Optional[Any] = None
    glucose_stats: Optional[GlucoseLevelStats] = None


PatientOverviewResponse = SuccessResponse[PatientOverview]
