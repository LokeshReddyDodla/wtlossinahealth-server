import uuid
from datetime import date
from typing import Optional
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientMedicalHistoryBase(BaseModel):
    condition: str
    condition_other: Optional[str] = None
    status: Optional[str] = None
    duration_years: float
    started_at: Optional[date] = None
    details: Optional[str] = None


class PatientMedicalHistoryCreate(PatientMedicalHistoryBase):
    pass


class PatientMedicalHistory(PatientMedicalHistoryBase):
    history_id: UUID
    patient_id: UUID

    class Config:
        from_attributes = True
