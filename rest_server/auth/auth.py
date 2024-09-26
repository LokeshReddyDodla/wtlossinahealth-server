from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.core.otp import create_and_send_otp, verify_otp
from lib.dependencies.database import get_postgres_session
from lib.models.patient import Patient
from lib.schemas.user import UserOTP, UserPhoneNumber
from lib.utils.auth_utils import AuthUtils
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
    user_otp: UserOTP,
    role: str,
    session: AsyncSession = Depends(get_postgres_session),
):
    try:
        cache_store = request.state.context.otp_store
        if await verify_otp(user_otp.phone_number, user_otp.otp, cache_store):
            auth_utils = AuthUtils(session)
            user, user_id, is_new_user = await auth_utils.get_or_create_user(
                user_otp.phone_number, role
            )
            token = create_jwt_token(
                user_id=user_id,
                role=role,
            )
            return OtpVerifySuccessResponse(
                message="OTP verified",
                data=OtpVerifyResponse(
                    token=token, user_id=user_id, is_new_user=is_new_user
                ),
            )
        else:
            response = ErrorResponse(
                message="Invalid OTP",
                detail="The OTP provided is incorrect.",
            )
            raise HTTPException(status_code=400, detail=response.dict())
    except HTTPException as e:
        raise e
    except Exception as e:
        return ErrorResponse(message="Failed to verify OTP", detail=str(e))
