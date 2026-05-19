import uuid
from datetime import date
from typing import Optional
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientMedicalHistoryBase(BaseModel):
    condition: str
    duration_years: float
    details: Optional[str] = None


class PatientMedicalHistoryCreate(PatientMedicalHistoryBase):
    condition_other: Optional[str] = None
    status: Optional[str] = None
    started_at: Optional[date] = None


class PatientMedicalHistory(PatientMedicalHistoryBase):
    history_id: UUID
    patient_id: UUID

    class Config:
        from_attributes = True
