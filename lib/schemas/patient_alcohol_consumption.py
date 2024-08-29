from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from uuid import UUID


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
        orm_mode = True
