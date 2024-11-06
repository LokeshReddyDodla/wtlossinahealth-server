from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from lib.core.types import OpenAIModelLiteral


class PatientTokenUsageLogBase(BaseModel):
    patient_id: UUID
    tokens_used: int
    model_used: OpenAIModelLiteral
    api_type: str  # e.g., 'openai', 'third_party'
    api_endpoint: str  # e.g., 'gpt-4o', 'image_classification'
    created_at: datetime

    class Config:
        from_attributes = True
        protected_namespaces = ()


class PatientTokenUsageLogCreate(PatientTokenUsageLogBase):
    pass


class PatientTokenUsageLogUpdate(PatientTokenUsageLogBase):
    pass


class PatientTokenUsageLog(PatientTokenUsageLogBase):
    id: UUID

    class Config:
        from_attributes = True
