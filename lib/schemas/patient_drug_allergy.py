import uuid
from typing import Optional
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientDrugAllergyBase(BaseModel):
    allergy_name: str
    name: Optional[str] = None
    name_other: Optional[str] = None
    reaction: Optional[str] = None


class PatientDrugAllergyCreate(PatientDrugAllergyBase):
    pass


class PatientDrugAllergy(PatientDrugAllergyBase):
    allergy_id: UUID
    patient_id: UUID

    class Config:
        from_attributes = True
