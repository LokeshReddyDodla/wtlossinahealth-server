from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from lib.utils.jwt import decode_jwt_token
from sqlalchemy.future import select
from app.models.user import User

security = HTTPBearer()

async def get_current_user(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    payload = decode_jwt_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user_id = payload["sub"]
    async with request.state.context.postgres_store.get_session() as session:
        result = await session.execute(
            select(User).where(User.user_id == user_id)
        )
        user = result.scalars().first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
    return user
