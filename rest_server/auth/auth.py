import traceback
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.core.otp import create_and_send_otp, verify_otp
from lib.core.types import ProfileTypeLiteral
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import get_user_device_service
from lib.models.patient import Patient
from lib.schemas.user import OtpVerificationData, UserPhoneNumber
from lib.services.user_device_service import UserDeviceService
from lib.utils.auth_utils import AuthUtils
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.jwt import create_jwt_token
from rest_server.auth.api_schema import (OtpVerifyResponse,
                                         OtpVerifySuccessResponse)
from rest_server.response_models import ErrorResponse, SuccessResponse

router = APIRouter()


@router.post("/send-otp", tags=["Auth"], response_model=SuccessResponse)
async def send_otp(request: Request, user_phone: UserPhoneNumber):
    try:
        cache_store = request.state.context.otp_store
        await create_and_send_otp(user_phone.phone_number, cache_store)
        return SuccessResponse(message="OTP sent successfully")
    except Exception as e:
        return ErrorResponse(message="Failed to generate OTP", detail=str(e))


@router.post(
    "/verify-otp",
    tags=["Auth"],
    response_model=OtpVerifySuccessResponse,
)
async def verify_otp_endpoint(
    request: Request,
    otp_data: OtpVerificationData,
    role: ProfileTypeLiteral,
    session: AsyncSession = Depends(get_postgres_session),
    user_device_service: UserDeviceService = Depends(get_user_device_service),
):
    try:
        cache_store = request.state.context.otp_store
        if await verify_otp(otp_data.phone_number, otp_data.otp, cache_store):
            # Create or get user using AuthUtils
            auth_utils = AuthUtils(session)
            user, user_id = await auth_utils.get_or_create_user(
                otp_data.phone_number, role
            )

            # Check if user is verified
            if not user.is_verified:  # type: ignore
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="User account is not verified.",
                )

            # Create JWT token for the user
            token = create_jwt_token(
                user_id=user_id,
                role=role,
            )

            # Store or update user device information if provided
            device = None
            if otp_data.fcm_token:
                device = (
                    await user_device_service.create_or_update_user_device(
                        user_id=UUID(user_id),
                        fcm_token=otp_data.fcm_token,
                        device_type=otp_data.device_type,
                        profile_type=role,
                        platform_version=otp_data.platform_version,
                    )
                )

            return OtpVerifySuccessResponse(
                message="OTP verified",
                data=OtpVerifyResponse(
                    token=token,
                    user_id=user_id,
                    device_id=str(device.device_id) if device else None,
                ),
            )
        else:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Invalid OTP.",
                detail="The OTP provided is incorrect.",
            )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to verify OTP.",
            detail=str(e),
        )


@router.post("/logout", tags=["Auth"], response_model=SuccessResponse)
async def logout(
    request: Request,
    device_id: Optional[str] = None,
    user_device_service: UserDeviceService = Depends(get_user_device_service),
):
    try:
        if not device_id:
            return SuccessResponse(
                message="No device ID provided, but logged out successfully."
            )

        await user_device_service.delete_user_device(UUID(device_id))
        return SuccessResponse(message="Logged out successfully")
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to log out.",
            detail=str(e),
        )
