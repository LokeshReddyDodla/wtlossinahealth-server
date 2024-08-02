from pydantic import BaseModel
from typing import Optional
from uuid import UUID


class PatientPermissionBase(BaseModel):
    camera_permission: Optional[bool] = False
    fitness_sync_permission: Optional[bool] = False
    audio_permission: Optional[bool] = False


class PatientPermissionCreate(PatientPermissionBase):
    pass


class PatientPermissionUpdate(PatientPermissionBase):
    pass


class PatientPermission(PatientPermissionBase):
    id: UUID

    class Config:
        orm_mode = True
