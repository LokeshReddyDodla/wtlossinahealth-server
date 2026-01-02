from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, RootModel

from lib.core.constants import CareProviderStatus


class CareProviderBase(BaseModel):
    # Personal Info
    first_name: str
    last_name: str
    profile_picture: Optional[str] = None
    phone_number: str
    email: str
    role: str

    # Medical Info
    medical_council_number: Optional[str] = None
    certificates: Optional[List[str]] = Field(default_factory=list)

    # System Fields
    permissions: Optional[Dict[str, Dict[str, bool]]] = None


class CareProviderCreate(CareProviderBase):
    pass


class CareProviderUpdate(CareProviderBase):
    code: str


class CareProvider(CareProviderBase):
    full_name: Optional[str]
    code: str
    care_provider_id: UUID
    status: CareProviderStatus = Field(default=CareProviderStatus.PENDING_VERIFICATION)
    is_verified: Optional[bool] = False
    created_at: datetime
    updated_at: datetime
    profile_completion: Optional[dict]

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


class PermissionActionSchema(BaseModel):
    read: bool = False
    create: bool = False
    update: bool = False
    delete: bool = False


class CareProviderPermissions(RootModel[Dict[str, PermissionActionSchema]]):
    def model_dump(self):
        return {feature: perms.model_dump() for feature, perms in self.root.items()}
