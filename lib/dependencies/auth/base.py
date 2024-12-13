from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from lib.utils.http_exceptions import raise_http_exception
from lib.utils.jwt import decode_jwt_token

security = HTTPBearer()


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    try:
        token = credentials.credentials

        payload = decode_jwt_token(token)
        if payload is None:
            raise_http_exception(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message="Invalid or expired token.",
            )

        user_id = payload.get("sub")
        role = payload.get("role")
        if user_id is None or role is None:
            raise_http_exception(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message="Invalid token. Missing user ID or role.",
            )

        return user_id, role

    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="An unexpected error occurred while decoding the token.",
            detail=str(e),
        )
