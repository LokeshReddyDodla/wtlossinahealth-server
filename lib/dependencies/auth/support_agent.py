"""Resolve a support-agent Actor.

Agents come from two roles:

- ``ProfileTypeEnum.ADMIN``                                    → product scope
- ``ProfileTypeEnum.CARE_PROVIDER`` with ``role == "support_staff"`` and a
  health_facility_id                                           → facility scope

Everyone else gets a 403.  The returned :class:`SupportAgent` exposes the
allowed scopes and the facility ids the agent can serve, so service-layer
queries can filter the queue in one place.
"""

from dataclasses import dataclass

from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload

from lib.core.constants import ProfileTypeEnum
from lib.core.types import SupportScopeLiteral
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.database import get_postgres_session
from lib.models.admin import Admin
from lib.models.care_provider import CareProvider
from lib.utils.http_exceptions import raise_http_exception


@dataclass
class SupportAgent:
    id: str
    role: ProfileTypeEnum
    allowed_scopes: list[SupportScopeLiteral]
    facility_ids: list[str]


SUPPORT_STAFF_ROLE = "support_staff"


async def get_support_agent_actor(
    request: Request,
    token_data: tuple = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> SupportAgent:
    user_id, role_value = token_data

    try:
        role = ProfileTypeEnum(role_value)
    except ValueError:
        raise_http_exception(
            status_code=status.HTTP_403_FORBIDDEN,
            message="Invalid role.",
        )

    if role == ProfileTypeEnum.ADMIN:
        admin = (
            await session.execute(select(Admin).where(Admin.id == user_id))
        ).scalars().first()
        if not admin or not admin.is_active:
            raise_http_exception(
                status_code=status.HTTP_403_FORBIDDEN,
                message="Admin account is not active.",
            )
        return SupportAgent(
            id=str(user_id),
            role=role,
            allowed_scopes=["product"],
            facility_ids=[],
        )

    if role == ProfileTypeEnum.CARE_PROVIDER:
        cp = (
            await session.execute(
                select(CareProvider)
                .where(CareProvider.care_provider_id == user_id)
                .options(joinedload(CareProvider.health_facility))
            )
        ).scalars().first()
        if not cp:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Care provider not found.",
            )
        if (cp.role or "").lower() != SUPPORT_STAFF_ROLE:
            raise_http_exception(
                status_code=status.HTTP_403_FORBIDDEN,
                message="Care provider is not a support agent.",
            )
        if not cp.health_facility_id:
            raise_http_exception(
                status_code=status.HTTP_403_FORBIDDEN,
                message="Support care provider has no facility assigned.",
            )
        return SupportAgent(
            id=str(user_id),
            role=role,
            allowed_scopes=["facility"],
            facility_ids=[str(cp.health_facility_id)],
        )

    raise_http_exception(
        status_code=status.HTTP_403_FORBIDDEN,
        message="This role cannot access support queues.",
    )
