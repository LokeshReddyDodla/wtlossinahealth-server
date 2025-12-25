from typing import List, Optional, Union
from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.database import get_postgres_session
from lib.models.admin import Admin
from lib.models.care_provider import CareProvider
from lib.models.patient import Patient
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
    has_care_provider_permission,
)
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.logging_utils import log_last_active_time


def get_current_user_flexible(
    allowed_types: List[ProfileTypeEnum],
    care_provider_action: Optional[CareProviderPermissionAction] = None,
    care_provider_feature: Optional[CareProviderFeature] = None,
    check_care_provider_permissions: bool = True,
    log_activity: bool = True,
):
    allowed_role_values = [pt.value for pt in allowed_types]
    
    async def dependency(
        request: Request,
        user_role: tuple = Depends(get_current_user),
        session: AsyncSession = Depends(get_postgres_session),
    ) -> Union[Patient, CareProvider, Admin]:
        user_id, role = user_role
        
        if role not in allowed_role_values:
            allowed_names = ", ".join([pt.name for pt in allowed_types])
            raise_http_exception(
                status_code=status.HTTP_403_FORBIDDEN,
                message=f"Access denied. Must be authenticated as one of: {allowed_names}",
            )
        
        # Handle Patient
        if role == ProfileTypeEnum.PATIENT.value:
            if ProfileTypeEnum.PATIENT not in allowed_types:
                raise_http_exception(
                    status_code=status.HTTP_403_FORBIDDEN,
                    message="Access denied. Patient access not allowed.",
                )
            
            result = await session.execute(
                select(Patient).where(Patient.patient_id == user_id)
            )
            patient = result.scalars().first()
            if not patient:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message=f"Patient with ID '{user_id}' not found.",
                )
            
            if log_activity:
                await log_last_active_time(
                    request,
                    session,
                    user_id,
                    ProfileTypeEnum.PATIENT,
                )
            
            return patient
        
        # Handle Care Provider
        elif role == ProfileTypeEnum.CARE_PROVIDER.value:
            if ProfileTypeEnum.CARE_PROVIDER not in allowed_types:
                raise_http_exception(
                    status_code=status.HTTP_403_FORBIDDEN,
                    message="Access denied. Care provider access not allowed.",
                )
            
            result = await session.execute(
                select(CareProvider)
                .where(CareProvider.care_provider_id == user_id)
                .options(joinedload(CareProvider.health_facility))
            )
            care_provider = result.scalars().first()
            if not care_provider:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Care Provider not found",
                )
            
            # Check permissions if required
            if check_care_provider_permissions:
                if care_provider_action is None or care_provider_feature is None:
                    raise ValueError(
                        "care_provider_action and care_provider_feature must be provided "
                        "when check_care_provider_permissions is True"
                    )
                
                if not has_care_provider_permission(
                    permissions=care_provider.permissions,  # type: ignore
                    feature=care_provider_feature,
                    action=care_provider_action,
                ):
                    raise_http_exception(
                        status_code=status.HTTP_403_FORBIDDEN,
                        message="Forbidden: Insufficient permissions",
                    )
            
            if log_activity:
                await log_last_active_time(
                    request,
                    session,
                    user_id,
                    ProfileTypeEnum.CARE_PROVIDER,
                )
            
            return care_provider
        
        # Handle Admin
        elif role == ProfileTypeEnum.ADMIN.value:
            if ProfileTypeEnum.ADMIN not in allowed_types:
                raise_http_exception(
                    status_code=status.HTTP_403_FORBIDDEN,
                    message="Access denied. Admin access not allowed.",
                )
            
            result = await session.execute(
                select(Admin).where(Admin.id == user_id)
            )
            admin = result.scalars().first()
            if not admin:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message=f"Admin with ID '{user_id}' not found.",
                )
            
            return admin
        
        # Should not reach here, but just in case
        raise_http_exception(
            status_code=status.HTTP_403_FORBIDDEN,
            message="Access denied. Invalid user role.",
        )
    
    return dependency

