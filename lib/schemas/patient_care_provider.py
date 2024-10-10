from datetime import datetime
from typing import Dict, Optional
from uuid import UUID

from pydantic import BaseModel

from lib.schemas.care_provider import CareProvider


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
    care_provider: Optional[CareProvider]
    assigned_at: datetime

    class Config:
        from_attributes = True

    @classmethod
    def from_orm(cls, obj):
        state = obj._sa_instance_state

        kwargs = {
            name: getattr(obj, name)
            for name in cls.model_fields
            if name in state.dict or name not in state.unloaded
        }

        return cls(**kwargs)
