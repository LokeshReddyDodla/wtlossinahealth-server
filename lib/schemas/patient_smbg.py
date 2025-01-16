from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class PatientSMBGBase(BaseModel):
    glucose_level: float
    reading_time: datetime
    source_name: str
    source_platform: str
    type: str  # pre_meal, post_meal, etc.
    notes: Optional[str] = None


class PatientSMBGCreate(PatientSMBGBase):
    pass


class PatientSMBGUpdate(PatientSMBGBase):
    pass


class PatientSMBG(PatientSMBGBase):
    id: UUID
    uploaded_at: datetime

    class Config:
        from_attributes = True
