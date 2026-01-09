from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.otp.otp_service import OTPService
from lib.core.otp.twilio_provider import TwilioOTPProvider
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
    SendOtpRequest,
    SendOtpResponse,
    VerifyOtpRequest,
    VerifyOtpResponse,
)
from .router import router


@router.post(
    "/send-otp",
    response_model=SendOtpResponse,
    summary="Send OTP",
    description="Send OTP to the provided phone number for authentication",
)
async def send_otp(
    request: Request,
    otp_request: SendOtpRequest,
) -> SendOtpResponse:
    try:
        cache_store = request.state.context.otp_store
        twilio_provider = TwilioOTPProvider()
        otp_service = OTPService(
            provider=twilio_provider, cache_store=cache_store
        )
        
        await otp_service.generate_and_send_otp(otp_request.phone_number)

        # Note: Currently returning fallback message due to WhatsApp limitations
        return SuccessResponse(
            message="Unable to send OTP on WhatsApp. Please enter the last 4 digits of your device number to proceed."
        )

    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Failed to generate OTP",
            detail=str(e),
        )


@router.post(
    "/verify-otp",
    response_model=VerifyOtpResponse,
    summary="Verify OTP",
    description="Verify OTP and authenticate user",
)
async def verify_otp(
    request: Request,
    verify_request: VerifyOtpRequest,
    role: ProfileTypeLiteral,
    session: AsyncSession = Depends(get_postgres_session),
    user_device_service: UserDeviceService = Depends(get_user_device_service),
) -> VerifyOtpResponse:
    try:
        cache_store = request.state.context.otp_store
        twilio_provider = TwilioOTPProvider()
        otp_service = OTPService(
            provider=twilio_provider, cache_store=cache_store
        )
        
        # Verify OTP
        is_valid = await otp_service.verify_otp(
            verify_request.phone_number,
            verify_request.otp,
            cache_only=True
        )
        
        if not is_valid:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Invalid OTP",
                detail="The OTP provided is incorrect.",
            )

        # Create or get user
        auth_utils = AuthUtils(session)
        user, user_id = await auth_utils.get_or_create_user(
            verify_request.phone_number, role
        )

        # Generate JWT token
        token = create_jwt_token(
            user_id=user_id,
            role=role,
        )

        # Store or update user device information
        device = await user_device_service.create_or_update_user_device(
            user_id=UUID(user_id),
            fcm_token=verify_request.fcm_token,
            profile_type=role,
            device_type=verify_request.device_type,
            platform_version=verify_request.platform_version,
            device_model=verify_request.device_model,
            manufacturer=verify_request.manufacturer,
            device_name=verify_request.device_name,
            is_physical_device=verify_request.is_physical_device,
            app_name=verify_request.app_name,
            app_version=verify_request.app_version,
            latitude=verify_request.latitude,
            longitude=verify_request.longitude,
            location_name=verify_request.location_name,
        )

        return SuccessResponse(
            message="OTP verified successfully",
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
            message="Failed to verify OTP",
            detail=str(e),
        )
