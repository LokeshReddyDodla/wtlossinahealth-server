from lib.models.patient import Patient
from lib.schemas.user import UserOTP, UserPhoneNumber
from fastapi import APIRouter, HTTPException, Request
from lib.core.otp import create_and_send_otp, verify_otp
from lib.utils.auth_utils import AuthUtils
from lib.utils.jwt import create_jwt_token
from rest_server.auth.api_schema import (
    OtpVerifyResponse,
    OtpVerifySuccessResponse,
)
from rest_server.response_models import ErrorResponse, SuccessResponse
from sqlalchemy.future import select


router = APIRouter()


@router.post("/generate-otp", tags=["Auth"], response_model=SuccessResponse)
async def generate_otp(request: Request, user_phone: UserPhoneNumber):
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
async def verify_otp_endpoint(request: Request, user_otp: UserOTP, role: str):
    try:
        cache_store = request.state.context.otp_store
        if await verify_otp(user_otp.phone_number, user_otp.otp, cache_store):
            async with request.state.context.postgres_store.get_session() as session:
                auth_utils = AuthUtils(session)
                user, user_id, is_new_user = (
                    await auth_utils.get_or_create_user(
                        user_otp.phone_number, role
                    )
                )
                token = create_jwt_token(
                    user_id=user_id,
                    role=role,
                )
                return OtpVerifySuccessResponse(
                    message="OTP verified",
                    data=OtpVerifyResponse(
                        token=token, is_new_user=is_new_user
                    ),
                )
        else:
            raise HTTPException(status_code=400, detail="Invalid OTP")
    except HTTPException as e:
        raise e
    except Exception as e:
        return ErrorResponse(message="Failed to verify OTP", detail=str(e))
