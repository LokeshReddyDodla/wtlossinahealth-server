from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel


class PackageBase(BaseModel):
    name: str


class PackageCreate(PackageBase):
    health_facility_id: UUID


class PackageUpdate(PackageBase):
    health_facility_id: Optional[UUID]


class Package(PackageBase):
    package_id: UUID
    created_at: datetime
    updated_at: datetime

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
