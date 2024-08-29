from typing import Optional
import uuid
from pydantic import BaseModel
from uuid import UUID
from lib.models import Base
from sqlalchemy.orm import relationship


class PatientPrescriptionBase(BaseModel):
    prescription_file: str


class PatientPrescriptionCreate(PatientPrescriptionBase):
    pass


class PatientPrescription(PatientPrescriptionBase):
    prescription_id: UUID
    medication_id: UUID

    class Config:
        orm_mode = True
