from typing import Optional
import uuid
from pydantic import BaseModel
from uuid import UUID
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
