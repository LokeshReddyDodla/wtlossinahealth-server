from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.database import get_postgres_session
from lib.models.care_provider import CareProvider
from lib.utils.care_provider_permissions import (CareProviderFeature,
                                                 CareProviderPermissionAction,
                                                 has_care_provider_permission)
from lib.utils.http_exceptions import raise_http_exception


def get_current_care_provider(
    action: CareProviderPermissionAction,
    feature: CareProviderFeature,
    check_permissions: bool = True,
):
    async def dependency(
        request: Request,
        user_role: tuple = Depends(get_current_user),
        session: AsyncSession = Depends(get_postgres_session),
    ):
        user_id, role = user_role

        if role != ProfileTypeEnum.CARE_PROVIDER.value:
            raise_http_exception(
                status_code=status.HTTP_403_FORBIDDEN,
                message="Not authorized as a Care Provider",
            )

        result = await session.execute(
            select(CareProvider)
            .where(CareProvider.care_provider_id == user_id)
            .options(
                selectinload(CareProvider.health_facility),
            )
        )
        care_provider = result.scalars().first()
        if not care_provider:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Care Provider not found",
            )

        if check_permissions and not has_care_provider_permission(
            permissions=care_provider.permissions,  # type: ignore
            feature=feature,
            action=action,
        ):
            raise_http_exception(
                status_code=status.HTTP_403_FORBIDDEN,
                message="Forbidden: Insufficient permissions",
            )

        return care_provider

    return dependency
