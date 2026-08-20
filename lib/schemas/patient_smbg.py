from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel

SMBGReadingType = Literal["fasting", "before_meal", "after_meal", "random"]


class PatientSMBGBase(BaseModel):
    glucose_level: float
    reading_time: datetime
    source_name: str
    source_platform: str
    type: SMBGReadingType
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
