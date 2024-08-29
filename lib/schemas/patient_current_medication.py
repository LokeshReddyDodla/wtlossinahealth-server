from typing import Optional
import uuid
from pydantic import BaseModel
from sqlalchemy import UUID, Column, ForeignKey, String
from lib.models import Base
from sqlalchemy.orm import relationship


class PatientCurrentMedicationBase(BaseModel):
    has_medication: bool
    prescription_description: Optional[str] = None
    prescription_image_url: Optional[str] = None


class PatientCurrentMedicationCreate(PatientCurrentMedicationBase):
    pass


class PatientCurrentMedication(PatientCurrentMedicationBase):
    medication_id: UUID
    patient_id: UUID

    class Config:
        orm_mode = True
