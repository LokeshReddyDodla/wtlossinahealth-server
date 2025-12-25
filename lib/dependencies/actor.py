from dataclasses import dataclass
from typing import Union, Optional

from lib.models.patient import Patient
from lib.models.care_provider import CareProvider
from lib.models.admin import Admin
from lib.core.constants import ProfileTypeEnum
from lib.utils.care_provider_permissions import CareProviderFeature, CareProviderPermissionAction, has_care_provider_permission
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.logging_utils import log_last_active_time
from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.database import get_postgres_session

ActorModel = Union[Patient, CareProvider, Admin]

@dataclass
class Actor:
    id: str
    role: ProfileTypeEnum
    model: ActorModel



def get_current_actor(
    *,
    allowed_roles: list[ProfileTypeEnum],
    care_provider_feature: CareProviderFeature | None = None,
    care_provider_action: CareProviderPermissionAction | None = None,
    check_permissions: bool = True,
    log_activity: bool = True,
):
    async def dependency(
        request: Request,
        token_data: tuple = Depends(get_current_user),
        session: AsyncSession = Depends(get_postgres_session),
    ) -> Actor:
        user_id, role_value = token_data
        role = ProfileTypeEnum(role_value)

        # 1️⃣ Role allowed?
        if role not in allowed_roles:
            raise_http_exception(
                status_code=status.HTTP_403_FORBIDDEN,
                message=f"Access denied for role: {role.name}",
            )

        # 2️⃣ Load model
        if role == ProfileTypeEnum.PATIENT:
            result = await session.execute(
                select(Patient).where(Patient.patient_id == user_id)
            )
            model = result.scalars().first()

        elif role == ProfileTypeEnum.CARE_PROVIDER:
            result = await session.execute(
                select(CareProvider)
                .where(CareProvider.care_provider_id == user_id)
                .options(joinedload(CareProvider.health_facility))
            )
            model = result.scalars().first()

            # 3️⃣ Permission check (only here)
            if check_permissions:
                if not care_provider_feature or not care_provider_action:
                    raise ValueError(
                        "care_provider_feature and care_provider_action required"
                    )

                if not has_care_provider_permission(
                    permissions=model.permissions,  # type: ignore
                    feature=care_provider_feature,
                    action=care_provider_action,
                ):
                    raise_http_exception(
                        status_code=status.HTTP_403_FORBIDDEN,
                        message="Forbidden: Insufficient permissions",
                    )

        elif role == ProfileTypeEnum.ADMIN:
            result = await session.execute(
                select(Admin).where(Admin.id == user_id)
            )
            model = result.scalars().first()

        else:
            raise_http_exception(
                status_code=status.HTTP_403_FORBIDDEN,
                message="Invalid role",
            )

        if not model:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message=f"{role.name} not found",
            )

        # 4️⃣ Activity logging (centralized)
        if log_activity:
            await log_last_active_time(
                request,
                session,
                user_id,
                role,
            )

        return Actor(
            id=str(user_id),
            role=role,
            model=model,
        )

    return dependency
