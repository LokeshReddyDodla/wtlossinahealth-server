import uuid
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel

from lib.models import Base
from lib.schemas.patient_diet_preference import (PatientDietPreference,
                                                 PatientDietPreferenceCreate)
from lib.schemas.patient_meal_timing import (PatientMealTiming,
                                             PatientMealTimingCreate)


class PatientEatingHabitBase(BaseModel):
    snacks_count: Optional[int] = None
    meals_per_day: Optional[int] = None
    dietary_preferences: Optional[List[str]] = None
    diet_preferences_detail: Optional[str] = None


class PatientEatingHabitCreate(PatientEatingHabitBase):
    meal_timings: Optional[List[PatientMealTimingCreate]] = []
    diet_preferences: Optional[PatientDietPreferenceCreate] = None
    cuisine_preferences: Optional[List[str]] = []


class PatientEatingHabit(PatientEatingHabitBase):
    eating_habit_id: UUID
    patient_id: UUID
    meal_timings: Optional[List[PatientMealTiming]] = []
    cuisine_preferences: Optional[List[str]] = []
    diet_preferences: Optional[PatientDietPreference] = None

    class Config:
        from_attributes = True

    @classmethod
    def from_orm(cls, obj):
        state = obj._sa_instance_state

        kwargs = {
            name: getattr(obj, name)
            for name in cls.model_fields
            if name in state.dict or name not in state.unloaded
        }

        return cls(**kwargs)
