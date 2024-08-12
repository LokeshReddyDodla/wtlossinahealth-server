from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID


class FitnessDataSyncBase(BaseModel):
    patient_id: UUID
    last_sync_timestamp: Optional[datetime] = None


class FitnessDataSyncCreate(FitnessDataSyncBase):
    pass


class FitnessDataSync(FitnessDataSyncBase):
    id: UUID

    class Config:
        orm_mode = True
