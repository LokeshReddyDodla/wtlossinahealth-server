from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from lib.core.types import ProfileTypeLiteral
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.schemas.patient import Patient as PatientSchema


class UserDeviceBase(BaseModel):
    user_id: UUID
    profile_type: ProfileTypeLiteral
    fcm_token: str
    device_type: Optional[str] = None  # e.g., 'iOS', 'Android'
    platform_version: Optional[str] = None
    last_updated_at: Optional[datetime] = None
    patient_id: Optional[UUID] = None
    care_provider_id: Optional[UUID] = None


class UserDeviceCreate(UserDeviceBase):
    pass


class UserDevice(UserDeviceBase):
    device_id: UUID
    patient: Optional[PatientSchema] = None
    care_provider: Optional[CareProviderSchema] = None

    class Config:
        orm_mode = True
