from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.core.constants import PROFILE_TYPE_CARE_PROVIDER
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.database import get_postgres_session
from lib.models.care_provider import CareProvider
from lib.utils.care_provider_permissions import CareProviderFeature


def get_current_care_provider(
    action: str,
    feature: CareProviderFeature,
    session: AsyncSession = Depends(get_postgres_session),
):
    async def dependency(
        request: Request,
        user_role: tuple = Depends(get_current_user),
    ):
        user_id, role = user_role

        if role != PROFILE_TYPE_CARE_PROVIDER:
            raise HTTPException(
                status_code=403, detail="Not authorized as a Care Provider"
            )

        result = await session.execute(
            select(CareProvider).where(
                CareProvider.care_provider_id == user_id
            )
        )
        care_provider = result.scalars().first()
        if not care_provider:
            raise HTTPException(
                status_code=404, detail="Care Provider not found"
            )

        permissions = care_provider.permissions
        feature_permissions = permissions.get(feature.value, {})
        if not feature_permissions.get(action, False):
            raise HTTPException(
                status_code=403,
                detail="Forbidden: Insufficient permissions",
            )

        return care_provider

    return dependency
