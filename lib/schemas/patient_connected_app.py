from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class PatientLibreViewBase(BaseModel):
    libreview_id: str
    last_sync_timestamp: Optional[datetime] = None
    connected_at: Optional[datetime] = None


class PatientLibreViewCreate(PatientLibreViewBase):
    pass


class PatientLibreView(PatientLibreViewBase):
    id: UUID

    class Config:
        from_attributes = True


class PatientOtherAppBase(BaseModel):
    other_app_id: str
    additional_field: Optional[str] = None
    connected_at: Optional[datetime] = None


class PatientOtherAppCreate(PatientOtherAppBase):
    pass


class PatientOtherApp(PatientOtherAppBase):
    id: UUID

    class Config:
        from_attributes = True


class PatientConnectedAppBase(BaseModel):
    patient_id: UUID


class PatientConnectedApp(PatientConnectedAppBase):
    id: UUID
    libreview: Optional[PatientLibreView] = None
    other_app: Optional[PatientOtherApp] = None

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
