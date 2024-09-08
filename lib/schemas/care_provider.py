from pydantic import BaseModel, HttpUrl
from typing import Optional, List, Dict
from datetime import datetime
from uuid import UUID

# from lib.schemas.health_facility import HealthFacility


class CareProviderBase(BaseModel):
    first_name: str
    last_name: str
    role: str
    profile_picture: Optional[HttpUrl] = None
    contact_number: str
    email: str
    permissions: Optional[Dict[str, bool]] = None
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


class CareProviderCreate(CareProviderBase):
    health_facility_id: UUID


class CareProviderUpdate(CareProviderBase):
    health_facility_id: Optional[UUID]


class CareProvider(CareProviderBase):
    care_provider_id: UUID
    
    # Lazy import inside the class definition
    @property
    def health_facility(self):
        from lib.schemas.health_facility import HealthFacility
        return HealthFacility

    class Config:
        orm_mode = True
