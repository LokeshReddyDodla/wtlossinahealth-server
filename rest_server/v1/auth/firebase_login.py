import asyncio
from uuid import UUID

import firebase_admin
from decouple import config
from fastapi import Depends, HTTPException, status
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials
from firebase_admin.exceptions import FirebaseError
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.types import ProfileTypeLiteral
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import get_user_device_service
from lib.services.user_device_service import UserDeviceService
from lib.utils.auth_utils import AuthUtils
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.jwt import create_jwt_token
from rest_server.response_models import SuccessResponse

from .api_schema import (
    AuthTokenResponse,
    FirebaseLoginRequest,
    FirebaseLoginResponse,
)
from .router import router


def _verify_firebase_token(id_token: str) -> dict:
    """Blocking (network cert fetch on cold start) — call via to_thread."""
    if not firebase_admin._apps:
        firebase_admin.initialize_app(
            credentials.Certificate(config("FCM_JSON_KEY_PATH"))
        )
    return firebase_auth.verify_id_token(id_token)


@router.post(
    "/firebase-login",
    response_model=FirebaseLoginResponse,
    summary="Login with Firebase phone auth",
    description="Verify a Firebase ID token (obtained after phone sign-in) "
    "and authenticate the user",
)
async def firebase_login(
    login_request: FirebaseLoginRequest,
    role: ProfileTypeLiteral,
    session: AsyncSession = Depends(get_postgres_session),
    user_device_service: UserDeviceService = Depends(get_user_device_service),
) -> FirebaseLoginResponse:
    try:
        decoded_token = await asyncio.to_thread(
            _verify_firebase_token, login_request.id_token
        )
    except (ValueError, FirebaseError) as e:
        raise_http_exception(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message="Invalid or expired Firebase token",
            detail=str(e),
        )

    # Patient rows store phone numbers without the leading '+'; Firebase
    # tokens carry E.164 — strip it or existing users get duplicate accounts.
    phone_number = (decoded_token.get("phone_number") or "").lstrip("+")
    if not phone_number:
        raise_http_exception(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message="Firebase token has no verified phone number",
        )

    try:
        auth_utils = AuthUtils(session)
        user, user_id = await auth_utils.get_or_create_user(phone_number, role)

        token = create_jwt_token(user_id=user_id, role=role)

        device = await user_device_service.create_or_update_user_device(
            user_id=UUID(user_id),
            fcm_token=login_request.fcm_token,
            profile_type=role,
            device_type=login_request.device_type,
            platform_version=login_request.platform_version,
            device_model=login_request.device_model,
            manufacturer=login_request.manufacturer,
            device_name=login_request.device_name,
            is_physical_device=login_request.is_physical_device,
            app_name=login_request.app_name,
            app_version=login_request.app_version,
            latitude=login_request.latitude,
            longitude=login_request.longitude,
            location_name=login_request.location_name,
        )

        return SuccessResponse(
            message="Login successful",
            data=AuthTokenResponse(
                token=token,
                user_id=user_id,
                device_id=str(device.device_id) if device else None,
            ),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to login",
            detail=str(e),
        )
