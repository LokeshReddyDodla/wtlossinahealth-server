from app.models.user import User
from app.schemas.user import UserOTP, UserPhoneNumber
from fastapi import APIRouter, Depends, HTTPException, Request
from lib.core.cache_store import CacheStore
from lib.core.otp import create_and_send_otp, verify_otp
from lib.utils.jwt import create_jwt_token
from pydantic import BaseModel
from rest_server.auth.api_schema import OTPRequest, OTPVerifyRequest
from rest_server.response_models import SuccessResponse
from sqlalchemy.orm import Session
from sqlalchemy.future import select


router = APIRouter()

@router.post("/generate-otp", tags=["Auth"])
async def generate_otp(request: Request, user_otp: UserPhoneNumber):
    cache_store = request.state.context.otp_store
    await create_and_send_otp(user_otp.phone_number, cache_store)
    return SuccessResponse(message="OTP sent successfully")

@router.post("/verify-otp", tags=["Auth"])
async def verify_otp_endpoint(request: Request, user_otp: UserOTP):
    cache_store = request.state.context.otp_store
    if await verify_otp(user_otp.phone_number, user_otp.otp, cache_store):
        async with request.state.context.postgres_store.get_session() as session:
            result = await session.execute(
                select(User).where(User.phone_number == user_otp.phone_number)
            )
            user = result.scalars().first()
            if not user:
                user = User(phone_number=user_otp.phone_number)
                session.add(user)
                await session.commit()
                await session.refresh(user)
            token = create_jwt_token(user)
            return SuccessResponse(message="OTP verified", data={"token": token})
    else:
        raise HTTPException(status_code=400, detail="Invalid OTP")