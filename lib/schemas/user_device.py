from datetime import datetime
from typing import Optional

from pydantic import UUID4, BaseModel


class UserDeviceBase(BaseModel):
    user_id: UUID4
    profile_type: str  # 'patient' or 'care_provider'
    fcm_token: str
    device_type: Optional[str] = None  # e.g., 'iOS', 'Android'
    platform_version: Optional[str] = None
    last_updated_at: Optional[datetime]

class UserDeviceCreate(UserDeviceBase):
    pass

class UserDevice(UserDeviceBase):
    device_id: UUID4

    class Config:
        orm_mode = True
