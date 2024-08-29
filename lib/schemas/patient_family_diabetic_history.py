from typing import Optional
import uuid
from pydantic import BaseModel
from uuid import UUID
from lib.models import Base
from sqlalchemy.orm import relationship


class PatientFamilyDiabeticHistoryBase(BaseModel):
    family_member: str


class PatientFamilyDiabeticHistoryCreate(PatientFamilyDiabeticHistoryBase):
    pass


class PatientFamilyDiabeticHistory(PatientFamilyDiabeticHistoryBase):
    history_id: UUID
    patient_id: UUID

    class Config:
        orm_mode = True
