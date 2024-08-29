from typing import Optional
import uuid
from pydantic import BaseModel
from uuid import UUID
from lib.models import Base
from sqlalchemy.orm import relationship


class PatientDietPreferenceBase(BaseModel):
    preference: str
    detail: Optional[str] = None


class PatientDietPreferenceCreate(PatientDietPreferenceBase):
    pass


class PatientDietPreference(PatientDietPreferenceBase):
    id: UUID
    patient_id: UUID

    class Config:
        orm_mode = True
