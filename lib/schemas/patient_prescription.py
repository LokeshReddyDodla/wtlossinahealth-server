import uuid
from typing import Optional
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientPrescriptionBase(BaseModel):
    prescription_file: str


class PatientPrescriptionCreate(PatientPrescriptionBase):
    pass


class PatientPrescription(PatientPrescriptionBase):
    prescription_id: UUID
    medication_id: UUID

    class Config:
        from_attributes = True
