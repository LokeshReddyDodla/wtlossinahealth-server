from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID


class PatientConnectedAppBase(BaseModel):
    patient_id: UUID


class PatientConnectedApp(PatientConnectedAppBase):
    id: UUID

    class Config:
        orm_mode = True


class LibreViewBase(BaseModel):
    libreview_id: str
    last_sync_timestamp: Optional[datetime] = None
    connected_at: Optional[datetime] = None


class LibreViewCreate(LibreViewBase):
    pass


class LibreView(LibreViewBase):
    id: UUID

    class Config:
        orm_mode = True


class OtherAppBase(BaseModel):
    other_app_id: str
    additional_field: Optional[str] = None
    connected_at: Optional[datetime] = None


class OtherAppCreate(OtherAppBase):
    pass


class OtherApp(OtherAppBase):
    id: UUID

    class Config:
        orm_mode = True
