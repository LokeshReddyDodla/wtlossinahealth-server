import uuid
from typing import Optional
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientDietPreferenceBase(BaseModel):
    preference: str
    detail: Optional[str] = None


class PatientDietPreferenceCreate(PatientDietPreferenceBase):
    pass


class PatientDietPreference(PatientDietPreferenceBase):
    id: UUID
    patient_id: UUID

    class Config:
        from_attributes = True
