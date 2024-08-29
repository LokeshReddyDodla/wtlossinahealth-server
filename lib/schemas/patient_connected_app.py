from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from uuid import UUID


class PatientLibreViewBase(BaseModel):
    libreview_id: str
    last_sync_timestamp: Optional[datetime] = None
    connected_at: Optional[datetime] = None


class PatientLibreViewCreate(PatientLibreViewBase):
    pass


class PatientLibreView(PatientLibreViewBase):
    id: UUID

    class Config:
        orm_mode = True


class PatientOtherAppBase(BaseModel):
    other_app_id: str
    additional_field: Optional[str] = None
    connected_at: Optional[datetime] = None


class PatientOtherAppCreate(PatientOtherAppBase):
    pass


class PatientOtherApp(PatientOtherAppBase):
    id: UUID

    class Config:
        orm_mode = True


class PatientConnectedAppBase(BaseModel):
    patient_id: UUID


class PatientConnectedApp(PatientConnectedAppBase):
    id: UUID
    libreview: Optional[PatientLibreView] = None
    other_app: Optional[PatientOtherApp] = None

    class Config:
        orm_mode = True
