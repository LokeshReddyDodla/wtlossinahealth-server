from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.core.constants import PROFILE_TYPE_ADMIN
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.database import get_postgres_session
from lib.models.admin import Admin


async def get_current_admin(
    request: Request,
    session: AsyncSession = Depends(get_postgres_session),
    user_role: tuple = Depends(get_current_user),
):
    user_id, role = user_role
    if role != PROFILE_TYPE_ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized")

    
    result = await session.execute(
        select(Admin).where(Admin.id == user_id)
    )
    admin = result.scalars().first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")
    return admin
