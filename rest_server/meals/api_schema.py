from lib.schemas.meal import MealDescription, MealResponse
from rest_server.response_models import SuccessResponse
from pydantic import BaseModel, Field, HttpUrl, constr
from typing import List, Optional
from datetime import datetime


class MealAnalysisResponse(SuccessResponse):
    data: Optional[MealResponse] = None


class MealsResponse(SuccessResponse):
    data: Optional[List[MealResponse]] = None


class MealUploadRequest(BaseModel):
    type: str
    time: datetime
    source: Optional[str] = "app"
    description: Optional[str] = None
    image_url: HttpUrl
