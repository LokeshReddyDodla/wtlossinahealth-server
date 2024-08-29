from typing import Optional
import uuid
from pydantic import BaseModel
from uuid import UUID
from lib.models import Base
from sqlalchemy.orm import relationship


class PatientFoodAllergyBase(BaseModel):
    allergy_name: str


class PatientFoodAllergyCreate(PatientFoodAllergyBase):
    pass


class PatientFoodAllergy(PatientFoodAllergyBase):
    allergy_id: UUID
    patient_id: UUID

    class Config:
        orm_mode = True
