from datetime import datetime
from typing import TYPE_CHECKING, Any, List, Optional
from uuid import UUID

from pydantic import BaseModel


class HealthFacilityBase(BaseModel):
    name: str
    logo_url: Optional[str] = None
    operating_hours: Optional[str] = None
    facility_type: Optional[str] = None
    website_url: Optional[str] = None
    specialties: Optional[str] = None
    latitude: Optional[str] = None
    longitude: Optional[str] = None
    parent_organization: Optional[str] = None
    emergency_contact: Optional[str] = None
    address: Optional[str] = None
    contact_info: Optional[str] = None
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
