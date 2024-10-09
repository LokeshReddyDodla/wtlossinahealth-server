import uuid
from typing import Optional
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import relationship

from lib.models import Base


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
        from_attributes = True
