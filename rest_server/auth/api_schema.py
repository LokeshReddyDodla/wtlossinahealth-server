from pydantic import BaseModel

from rest_server.response_models import SuccessResponse


class OTPRequest(BaseModel):
    phone_number: str


class OTPVerifyRequest(BaseModel):
    phone_number: str
    otp: str


class OtpVerifyResponse(BaseModel):
    token: str
    user_id: str
    device_id: str
    is_new_user: bool


OtpVerifySuccessResponse = SuccessResponse[OtpVerifyResponse]
