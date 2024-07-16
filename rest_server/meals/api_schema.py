from lib.schemas.meal import MealDescription, MealResponse
from rest_server.response_models import SuccessResponse
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class MealAnalysisResponse(SuccessResponse):
    data: MealResponse


class MealUploadRequest(BaseModel):
    type: str
    time: datetime
    source: Optional[str] = "app"
    description: Optional[str] = None
    image_url: str
