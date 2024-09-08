from pydantic import BaseModel, HttpUrl
from typing import Optional, List
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

    # Lazy import inside the class definition
    @property
    def care_providers(self):
        from lib.schemas.care_provider import CareProvider

        return [CareProvider]

    class Config:
        orm_mode = True
