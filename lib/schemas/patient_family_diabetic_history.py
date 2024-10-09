import uuid
from typing import Optional
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientFamilyDiabeticHistoryBase(BaseModel):
    family_member: str


class PatientFamilyDiabeticHistoryCreate(PatientFamilyDiabeticHistoryBase):
    pass


class PatientFamilyDiabeticHistory(PatientFamilyDiabeticHistoryBase):
    history_id: UUID
    patient_id: UUID

    class Config:
        from_attributes = True
