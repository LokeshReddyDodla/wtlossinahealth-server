from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.database import get_postgres_session
from lib.models.admin import Admin
from lib.utils.http_exceptions import raise_http_exception


async def get_current_admin(
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
    user_role: tuple = Depends(get_current_user),
):
    try:
        user_id, role = user_role
        if role != ProfileTypeEnum.ADMIN.value:
            raise_http_exception(
                status_code=status.HTTP_403_FORBIDDEN,
                message="Access denied. User is not authorized as an admin.",
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

    except HTTPException as http_exc:
        raise http_exc

    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="An unexpected error occurred while retrieving the current admin.",
            detail=str(e),
        )
