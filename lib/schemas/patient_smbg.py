from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID


class PatientSMBGBase(BaseModel):
    glucose_level: float
    reading_time: datetime
    source: str
    type: str  # pre_meal, post_meal, etc.
    meal_type: Optional[str] = None  # breakfast, lunch, dinner, snack, etc.
    notes: Optional[str] = None


class PatientSMBGCreate(PatientSMBGBase):
    pass


class PatientSMBGUpdate(PatientSMBGBase):
    pass


class PatientSMBG(PatientSMBGBase):
    id: UUID
    uploaded_at: datetime

    class Config:
        orm_mode = True
