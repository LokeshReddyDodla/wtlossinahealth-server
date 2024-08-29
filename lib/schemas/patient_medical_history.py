from typing import Optional
import uuid
from pydantic import BaseModel
from sqlalchemy import UUID, Column, ForeignKey, String
from lib.models import Base
from sqlalchemy.orm import relationship


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
        orm_mode = True
