from fastapi import Depends, HTTPException, Request
from sqlalchemy.future import select

from lib.dependencies.auth.base import get_current_user
from lib.models.admin import Admin


async def get_current_admin(
    request: Request,
    user_role: tuple = Depends(get_current_user),
):
    user_id, role = user_role
    if role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    async with request.state.context.postgres_store.get_session() as session:
        result = await session.execute(
            select(Admin).where(Admin.id == user_id)
        )
        admin = result.scalars().first()
        if not admin:
            raise HTTPException(status_code=404, detail="Admin not found")
    return admin
