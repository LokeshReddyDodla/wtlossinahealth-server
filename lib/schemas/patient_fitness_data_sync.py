from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class PatientFitnessDataSyncBase(BaseModel):
    patient_id: UUID
    last_sync_timestamp: Optional[datetime] = None


class PatientFitnessDataSyncCreate(PatientFitnessDataSyncBase):
    pass


class PatientFitnessDataSync(PatientFitnessDataSyncBase):
    id: UUID

    class Config:
        from_attributes = True
