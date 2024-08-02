from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID


class PatientVitalsBase(BaseModel):
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


class PatientVitalsCreate(PatientVitalsBase):
    pass


class PatientVitalsUpdate(PatientVitalsBase):
    pass


class PatientVitals(PatientVitalsBase):
    id: UUID
    uploaded_at: datetime

    class Config:
        orm_mode = True
