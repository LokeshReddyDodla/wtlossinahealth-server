from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, HttpUrl, constr

from lib.schemas.meal_stats import DailyMealStats
from lib.schemas.patient_meal import PatientMeal
from rest_server.response_models import SuccessResponse


class PatientMealResponse(PatientMeal):
    @classmethod
    def from_orm(cls, obj):
        state = obj._sa_instance_state

        kwargs = {
            name: getattr(obj, name)
            for name in cls.model_fields
            if name in state.dict or name not in state.unloaded
        }

        return cls(**kwargs)


PatientMealsResponse = SuccessResponse[List[PatientMealResponse]]

PatientMealStatsResponse = SuccessResponse[DailyMealStats]


class PatientMealUploadRequest(BaseModel):
    type: str
    datetime: datetime
    source: Optional[str] = "app"
    description: Optional[str] = None
    image_url: HttpUrl


PatientMealAnalysisResponse = SuccessResponse[PatientMealResponse]

PatientMealUploadResponse = SuccessResponse[PatientMealResponse]
