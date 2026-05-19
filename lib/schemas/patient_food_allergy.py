import uuid
from typing import Optional
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientFoodAllergyBase(BaseModel):
    allergy_name: str


class PatientFoodAllergyCreate(PatientFoodAllergyBase):
    name: Optional[str] = None
    name_other: Optional[str] = None
    severity: Optional[str] = None


class PatientFoodAllergy(PatientFoodAllergyBase):
    allergy_id: UUID
    patient_id: UUID

    class Config:
        from_attributes = True
