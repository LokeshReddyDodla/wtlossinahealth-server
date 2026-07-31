from typing import Optional
from uuid import UUID

from fastapi import Depends
from pydantic import BaseModel, model_validator

from lib.core.constants import AIFeatureEnum, AIToggleScopeEnum
from lib.dependencies.auth.admin_auth import get_current_admin
from lib.models.admin import Admin
from lib.services.ai_feature_toggle_service import ai_feature_toggle_service
from rest_server.response_models import SuccessResponse

from .router import router


class SetToggleRequest(BaseModel):
    feature: AIFeatureEnum
    scope: AIToggleScopeEnum
    scope_id: Optional[UUID] = None  # health_facility_id for facility scope
    enabled: bool
    reason: Optional[str] = None

    @model_validator(mode="after")
    def _validate_scope(self) -> "SetToggleRequest":
        if self.scope == AIToggleScopeEnum.FACILITY and self.scope_id is None:
            raise ValueError("scope_id (facility id) is required for facility scope")
        if self.scope == AIToggleScopeEnum.SYSTEM and self.scope_id is not None:
            raise ValueError("scope_id must be omitted for system scope")
        if (
            self.feature == AIFeatureEnum.PRODUCT_BOT
            and self.scope == AIToggleScopeEnum.FACILITY
        ):
            raise ValueError("product_bot can only be toggled at system scope")
        return self


@router.post("", response_model=SuccessResponse)
async def set_ai_feature_toggle(
    payload: SetToggleRequest,
    current_admin: Admin = Depends(get_current_admin),
) -> SuccessResponse:
    await ai_feature_toggle_service.set_toggle(
        feature=payload.feature.value,
        scope=payload.scope.value,
        scope_id=payload.scope_id,
        enabled=payload.enabled,
        reason=payload.reason,
        admin_id=current_admin.id,
    )
    verb = "enabled" if payload.enabled else "paused"
    scope_desc = (
        "system-wide"
        if payload.scope == AIToggleScopeEnum.SYSTEM
        else f"for facility {payload.scope_id}"
    )
    return SuccessResponse(
        message=f"'{payload.feature.value}' {verb} {scope_desc}",
    )
