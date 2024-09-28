from typing import Optional

from pydantic import BaseModel, Field


class UserPhoneNumber(BaseModel):
    phone_number: str


class OtpVerificationData(BaseModel):
    phone_number: str
    otp: str
    fcm_token: str = Field(None, description="FCM token of the user's device")
    device_type: str = Field(
        None, description="Type of the user's device (e.g., iOS, Android)"
    )
