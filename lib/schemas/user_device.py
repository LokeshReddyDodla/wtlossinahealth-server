from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class UserDeviceBase(BaseModel):
    user_id: UUID
    profile_type: str  # 'patient' or 'care_provider'
    fcm_token: str
    device_type: Optional[str] = None  # e.g., 'iOS', 'Android'
    platform_version: Optional[str] = None
    last_updated_at: Optional[datetime] = None

class UserDeviceCreate(UserDeviceBase):
    pass

class UserDevice(UserDeviceBase):
    device_id: UUID

    class Config:
        orm_mode = True
