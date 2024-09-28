from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, HttpUrl

from lib.schemas.health_facility import HealthFacility
from lib.schemas.user_device import UserDevice


class CareProviderBase(BaseModel):
    first_name: str
    last_name: str
    role: str
    profile_picture: Optional[HttpUrl] = None
    phone_number: str
    email: str
    permissions: Optional[Dict[str, Dict[str, bool]]] = None
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


class CareProviderCreate(CareProviderBase):
    health_facility_id: UUID


class CareProviderUpdate(CareProviderBase):
    health_facility_id: Optional[UUID]


class CareProvider(CareProviderBase):
    care_provider_id: UUID
    health_facility: Optional[HealthFacility] = None
    patient_relationships: Optional[List[Any]] = []  # PatientCareProvider
    user_devices: List[UserDevice] = []
    

    class Config:
        orm_mode = True

    @classmethod
    def from_orm(cls, obj):
        state = obj._sa_instance_state

        kwargs = {
            name: getattr(obj, name)
            for name in cls.__fields__
            if name in state.dict or name not in state.unloaded
        }

        return cls(**kwargs)
