import uuid
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientMealTimingBase(BaseModel):
    meal_type: str
    time: str

class PatientMealTimingCreate(PatientMealTimingBase):
    pass

class PatientMealTiming(PatientMealTimingBase):
    id: UUID
    patient_id: UUID

    class Config:
        from_attributes = True