from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, HttpUrl


class PatientLibreViewBase(BaseModel):
    libreview_id: str


class PatientLibreViewCreate(PatientLibreViewBase):
    pass


class PatientLibreView(PatientLibreViewBase):
    id: UUID
    last_sync_timestamp: Optional[datetime] = None
    connected_at: datetime

    class Config:
        from_attributes = True


class PatientOtherAppBase(BaseModel):
    other_app_id: str
    additional_field: Optional[str] = None


class PatientOtherAppCreate(PatientOtherAppBase):
    pass


class PatientOtherApp(PatientOtherAppBase):
    id: UUID
    connected_at: datetime

    class Config:
        from_attributes = True


class PatientConnectedAppBase(BaseModel):
    patient_id: UUID


class PatientSchema(BaseModel):
    patient_id: UUID
    first_name: Optional[str]
    last_name: Optional[str]
    gender: Optional[str]
    profile_picture: Optional[HttpUrl] = None
    email: Optional[str]

    class Config:
        from_attributes = True


class PatientConnectedApp(PatientConnectedAppBase):

    id: UUID
    libreview: Optional[PatientLibreView] = None
    other_app: Optional[PatientOtherApp] = None
    # patient: Optional[PatientSchema] = None

    class Config:
        from_attributes = True

    @classmethod
    def from_orm(cls, obj):
        state = obj._sa_instance_state

        kwargs = {
            name: getattr(obj, name)
            for name in cls.model_fields
            if name in state.dict or name not in state.unloaded
        }

        return cls(**kwargs)
