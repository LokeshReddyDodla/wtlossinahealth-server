from pydantic import BaseModel
from typing import Optional, Dict
from uuid import UUID


class PatientCareProviderBase(BaseModel):
    patient_id: UUID
    care_provider_id: UUID
    roles: Optional[Dict[str, bool]] = None


class PatientCareProviderCreate(PatientCareProviderBase):
    pass


class PatientCareProviderUpdate(PatientCareProviderBase):
    pass


class PatientCareProvider(PatientCareProviderBase):
    patient_care_provider_id: UUID

    class Config:
        orm_mode = True
