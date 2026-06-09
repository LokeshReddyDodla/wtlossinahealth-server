from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


class PatientAlcoholConsumptionBase(BaseModel):
    consume_alcohol: Optional[bool] = None
    status: Optional[str] = None
    frequency: Optional[str] = None
    quantity: Optional[str] = None
    drinks_per_session: Optional[int] = None
    type_of_alcohol: Optional[List[str]] = None
    quit_years_ago: Optional[int] = None


class PatientAlcoholConsumptionCreate(PatientAlcoholConsumptionBase):
    pass


class PatientAlcoholConsumption(PatientAlcoholConsumptionBase):
    id: UUID
    patient_id: UUID

    class Config:
        from_attributes = True
