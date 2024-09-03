from lib.schemas.patient_meal import PatientMeal
from rest_server.response_models import SuccessResponse
from pydantic import BaseModel, Field, HttpUrl, constr
from typing import List, Optional
from datetime import datetime


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


PatientMealsResponse = SuccessResponse[List[PatientMealResponse]]


class PatientMealUploadRequest(BaseModel):
    type: str
    datetime: datetime
    source: Optional[str] = "app"
    description: Optional[str] = None
    image_url: HttpUrl


PatientMealAnalysisResponse = SuccessResponse[PatientMealResponse]

PatientMealUploadResponse = SuccessResponse[PatientMealResponse]
