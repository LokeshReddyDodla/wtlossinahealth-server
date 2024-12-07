from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel

from lib.schemas.health_facility import HealthFacility


class CareProviderBase(BaseModel):
    first_name: str
    last_name: str
    role: str
    profile_picture: Optional[str] = None
    phone_number: str
    email: str
    permissions: Optional[Dict[str, Dict[str, bool]]] = None


class CareProviderCreate(CareProviderBase):
    health_facility_id: UUID


class CareProviderUpdate(CareProviderBase):
    health_facility_id: Optional[UUID]


class CareProvider(CareProviderBase):
    care_provider_id: UUID
    is_verified: Optional[bool] = False
    created_at: datetime
    updated_at: datetime
    profile_completion: Optional[dict]

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
