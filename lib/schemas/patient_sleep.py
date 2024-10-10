from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class PatientSleepSchema(BaseModel):
    id: UUID
    source: str
    sleep_duration: float  # Duration in minutes or hours
    sleep_start_time: datetime
    sleep_end_time: datetime
    uploaded_at: datetime

    class Config:
        from_attributes = True
