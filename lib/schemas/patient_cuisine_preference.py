import uuid
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientCuisinePreferenceBase(BaseModel):
    cuisine: str


class PatientCuisinePreferenceCreate(PatientCuisinePreferenceBase):
    pass


class PatientCuisinePreference(PatientCuisinePreferenceBase):
    id: UUID
    eating_habit_id: UUID

    class Config:
        from_attributes = True
