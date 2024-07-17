from lib.models.patient import Patient
from lib.schemas.user import UserOTP, UserPhoneNumber
from fastapi import APIRouter, HTTPException, Request
from lib.core.otp import create_and_send_otp, verify_otp
from lib.utils.jwt import create_jwt_token
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


@router.post("/verify-otp", tags=["Auth"], response_model=SuccessResponse)
async def verify_otp_endpoint(request: Request, user_otp: UserOTP, role: str):
    try:
        cache_store = request.state.context.otp_store
        if await verify_otp(user_otp.phone_number, user_otp.otp, cache_store):
            async with request.state.context.postgres_store.get_session() as session:
                user, user_id = await get_or_create_user(
                    session, user_otp.phone_number, role
                )
                token = create_jwt_token(
                    user_id=user_id,
                    phone_number=str(user.phone_number),
                    role=role,
                )
                return SuccessResponse(
                    message="OTP verified", data={"token": token}
                )
        else:
            raise HTTPException(status_code=400, detail="Invalid OTP")
    except HTTPException as e:
        raise e
    except Exception as e:
        return ErrorResponse(message="Failed to verify OTP", detail=str(e))


async def get_or_create_user(session, phone_number: str, role: str):
    if role == "Patient":
        result = await session.execute(
            select(Patient).where(Patient.phone_number == phone_number)
        )
        user = result.scalars().first()
        if not user:
            user = Patient(phone_number=phone_number)
            session.add(user)
            await session.commit()
            await session.refresh(user)
        user_id = str(user.patient_id)
    elif role == "Doctor":
        pass
    else:
        raise HTTPException(status_code=400, detail="Invalid role")
    return user, user_id
