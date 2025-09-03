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
    fcm_token: Optional[str] = None
    device_type: Optional[str] = None  # e.g., 'iOS', 'Android'
    platform_version: Optional[str] = None
    device_model: Optional[str] = None
    manufacturer: Optional[str] = None
    device_name: Optional[str] = None
    is_physical_device: Optional[bool] = None
    app_name: Optional[str] = None
    app_version: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_name: Optional[str] = None

    last_updated_at: Optional[datetime] = None
    last_active_at: Optional[datetime] = None


class UserDeviceCreate(UserDeviceBase):
    pass


class UserDevice(UserDeviceBase):
    device_id: UUID
    patient: Optional[PatientSchema] = None
    care_provider: Optional[CareProviderSchema] = None

    class Config:
        from_attributes = True
