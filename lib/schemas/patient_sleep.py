from pydantic import BaseModel
from datetime import datetime
from typing import Optional

from uuid import UUID


class PatientSleepSchema(BaseModel):
    id: UUID
    source: str
    sleep_duration: float  # Duration in minutes or hours
    sleep_start_time: datetime
    sleep_end_time: datetime
    uploaded_at: datetime

    class Config:
        orm_mode = True
