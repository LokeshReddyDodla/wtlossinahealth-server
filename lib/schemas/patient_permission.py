from datetime import datetime
from pydantic import BaseModel
from typing import Optional
from uuid import UUID


class PatientPermissionBase(BaseModel):
    notification_permission: Optional[bool] = False
    health_permission: Optional[bool] = False
    camera_permission: Optional[bool] = False
    storage_permission: Optional[bool] = False
    last_sync_time: Optional[datetime]


class PatientPermissionCreate(PatientPermissionBase):
    pass


class PatientPermissionUpdate(PatientPermissionBase):
    pass


class PatientPermission(PatientPermissionBase):
    id: UUID

    class Config:
        orm_mode = True
