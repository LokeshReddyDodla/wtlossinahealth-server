import uuid
from pydantic import BaseModel
from lib.models import Base
from sqlalchemy.orm import relationship
from uuid import UUID


class PatientCuisinePreferenceBase(BaseModel):
    cuisine: str


class PatientCuisinePreferenceCreate(PatientCuisinePreferenceBase):
    pass


class PatientCuisinePreference(PatientCuisinePreferenceBase):
    id: UUID
    patient_id: UUID

    class Config:
        orm_mode = True
