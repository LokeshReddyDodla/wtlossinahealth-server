from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CareProviderBase(BaseModel):
    # Personal Info
    first_name: str
    last_name: str
    profile_picture: Optional[str] = None
    phone_number: str
    email: str
    role: str

    # Clinic Info
    clinic_name: Optional[str] = None
    clinic_phone_number: Optional[str] = None
    clinic_address: Optional[str] = None
    clinic_website_url: Optional[str] = None

    # Medical Info
    medical_council_number: Optional[str] = None
    certificates: Optional[List[Dict[str, Any]]] = Field(default_factory=list)

    # System Fields
    permissions: Optional[Dict[str, Dict[str, bool]]] = None


class CareProviderCreate(CareProviderBase):
    pass


class CareProviderUpdate(CareProviderBase):
    pass


class CareProvider(CareProviderBase):
    code: str
    care_provider_id: UUID
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


class CareProviderPermissions(BaseModel):
    __root__: Dict[str, PermissionActionSchema]

    def model_dump(self):
        return {feature: perms.dict() for feature, perms in self.__root__.items()}
