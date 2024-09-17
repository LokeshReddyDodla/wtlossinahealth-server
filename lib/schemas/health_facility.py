from pydantic import BaseModel, HttpUrl
from typing import TYPE_CHECKING, Any, Optional, List
from datetime import datetime
from uuid import UUID


class HealthFacilityBase(BaseModel):
    name: str
    address: str
    contact_info: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


class HealthFacilityCreate(HealthFacilityBase):
    pass


class HealthFacilityUpdate(HealthFacilityBase):
    pass


class HealthFacility(HealthFacilityBase):
    health_facility_id: UUID
    care_providers: Optional[List[Any]] = None  # CareProvider
    patients: Optional[List[Any]] = None  # Patient

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
