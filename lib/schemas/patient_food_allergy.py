from typing import Optional
import uuid
from pydantic import BaseModel
from sqlalchemy import UUID, Column, ForeignKey, String
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
