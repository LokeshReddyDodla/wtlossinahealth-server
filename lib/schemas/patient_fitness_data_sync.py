from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID


class PatientFitnessDataSyncBase(BaseModel):
    patient_id: UUID
    last_sync_timestamp: Optional[datetime] = None


class PatientFitnessDataSyncCreate(PatientFitnessDataSyncBase):
    pass


class PatientFitnessDataSync(PatientFitnessDataSyncBase):
    id: UUID

    class Config:
        orm_mode = True
