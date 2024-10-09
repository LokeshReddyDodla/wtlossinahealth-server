from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class PatientVitalBase(BaseModel):
    source: str
    test_time: datetime
    a1c: Optional[float] = None
    creatinine: Optional[float] = None
    diastolic_bp: Optional[float] = None
    heart_rate: Optional[float] = None
    ketones: Optional[float] = None
    respiratory_rate: Optional[float] = None
    spo2: Optional[float] = None
    systolic_bp: Optional[float] = None
    temperature: Optional[float] = None
    weight: Optional[float] = None


class PatientVitalCreate(PatientVitalBase):
    pass


class PatientVitalUpdate(PatientVitalBase):
    pass


class PatientVital(PatientVitalBase):
    id: UUID
    uploaded_at: datetime

    class Config:
        from_attributes = True
