import uuid
from typing import Optional
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientFamilyDiabeticHistoryBase(BaseModel):
    family_member: str
    years_with_diabetes: Optional[float] = None


class PatientFamilyDiabeticHistoryCreate(PatientFamilyDiabeticHistoryBase):
    type_of_diabetes: Optional[str] = None


class PatientFamilyDiabeticHistory(PatientFamilyDiabeticHistoryBase):
    history_id: UUID
    patient_id: UUID

    class Config:
        from_attributes = True
