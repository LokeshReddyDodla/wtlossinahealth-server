
from pydantic import BaseModel, HttpUrl
from typing import Optional, List
from datetime import datetime
from uuid import UUID

# from lib.schemas.care_provider import CareProvider

class HealthFacilityBase(BaseModel):
    name: str
    address: str
    contact_number: str
    email: Optional[str] = None
    website: Optional[HttpUrl] = None
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

class HealthFacilityCreate(HealthFacilityBase):
    pass

class HealthFacilityUpdate(HealthFacilityBase):
    pass

class HealthFacility(HealthFacilityBase):
    health_facility_id: UUID
    # care_providers: List[CareProvider] = []
    
    # Lazy import inside the class definition
    @property
    def care_providers(self):
        from lib.schemas.care_provider import CareProvider
        return [CareProvider]

    class Config:
        orm_mode = True
