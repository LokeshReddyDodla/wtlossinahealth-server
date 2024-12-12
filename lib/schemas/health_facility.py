from datetime import datetime
from typing import TYPE_CHECKING, Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, constr

from lib.schemas.package import Package


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


class HealthFacilityCreate(HealthFacilityBase):
    subdomain: Optional[str] = Field(
        None,
        pattern=r"^[a-z0-9-]+$",
        max_length=63,
        description="Generated subdomain (lowercase, alphanumeric, and hyphens only)",
    )
    custom_domain: Optional[str] = Field(
        default="aihealth.clinic",
        description="Custom domain for the health facility",
    )


class HealthFacilityUpdate(HealthFacilityBase):
    subdomain: Optional[str] = Field(
        None,
        pattern=r"^[a-z0-9-]+$",
        max_length=63,
        description="Generated subdomain (lowercase, alphanumeric, and hyphens only)",
    )
    custom_domain: Optional[str] = None


class HealthFacility(HealthFacilityBase):
    health_facility_id: UUID
    subdomain: Optional[str]
    custom_domain: Optional[str]
    created_at: datetime
    updated_at: datetime
    packages: Optional[Package]

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
