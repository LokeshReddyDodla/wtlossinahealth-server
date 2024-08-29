import uuid
from pydantic import BaseModel
from uuid import UUID
from lib.models import Base
from sqlalchemy.orm import relationship


class PatientMealTimingBase(BaseModel):
    meal_type: str
    time: str

class PatientMealTimingCreate(PatientMealTimingBase):
    pass

class PatientMealTiming(PatientMealTimingBase):
    id: UUID
    patient_id: UUID

    class Config:
        orm_mode = True