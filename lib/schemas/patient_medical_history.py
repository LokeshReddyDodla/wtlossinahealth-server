import uuid
from typing import Optional
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientMedicalHistoryBase(BaseModel):
    condition: str
    duration_years: int
    details: Optional[str] = None


class PatientMedicalHistoryCreate(PatientMedicalHistoryBase):
    pass


class PatientMedicalHistory(PatientMedicalHistoryBase):
    history_id: UUID
    patient_id: UUID

    class Config:
        from_attributes = True
