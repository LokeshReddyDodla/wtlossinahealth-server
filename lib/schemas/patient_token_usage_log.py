from datetime import datetime
from pydantic import BaseModel
from uuid import UUID


class PatientTokenUsageLogBase(BaseModel):
    patient_id: UUID
    tokens_used: int
    api_type: str  # e.g., 'openai', 'third_party'
    api_endpoint: str  # e.g., 'gpt-4o', 'image_classification'
    created_at: datetime

    class Config:
        orm_mode = True


class PatientTokenUsageLogCreate(PatientTokenUsageLogBase):
    pass


class PatientTokenUsageLogUpdate(PatientTokenUsageLogBase):
    pass


class PatientTokenUsageLog(PatientTokenUsageLogBase):
    id: UUID

    class Config:
        orm_mode = True
