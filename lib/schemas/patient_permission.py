from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class PatientPermissionBase(BaseModel):
    notification_permission: Optional[bool] = False
    health_permission: Optional[bool] = False
    camera_permission: Optional[bool] = False
    gallery_permission: Optional[bool] = False
    storage_permission: Optional[bool] = False


class PatientPermissionCreate(PatientPermissionBase):
    pass


class PatientPermissionUpdate(PatientPermissionBase):
    pass


class PatientPermission(PatientPermissionBase):
    id: UUID
    last_sync_time: Optional[datetime]

    class Config:
        from_attributes = True
