from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


class PatientAlcoholConsumptionBase(BaseModel):
    consume_alcohol: bool
    frequency: Optional[str] = None
    quantity: Optional[str] = None
    type_of_alcohol: Optional[List[str]] = None


class PatientAlcoholConsumptionCreate(PatientAlcoholConsumptionBase):
    pass


class PatientAlcoholConsumption(PatientAlcoholConsumptionBase):
    id: UUID
    patient_id: UUID

    class Config:
        from_attributes = True
