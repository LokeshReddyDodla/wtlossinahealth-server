from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel
from enum import Enum


class PackageStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DRAFT = "draft"
    DEPRECATED = "deprecated"


class PackageBase(BaseModel):
    name: str
    status: Optional[PackageStatus] = PackageStatus.ACTIVE
    duration_days: int
    price: Optional[int] = None
    description: Optional[str] = None
    features: Optional[dict] = None
    package_type: Optional[str] = None


class PackageCreate(PackageBase):
    pass


class PackageUpdate(PackageBase):
    pass


class Package(PackageBase):
    package_id: UUID
    code: str
    health_facility_id: UUID
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
