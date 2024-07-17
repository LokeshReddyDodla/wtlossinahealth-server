from pydantic import BaseModel


class UserPhoneNumber(BaseModel):
    phone_number: str


class UserOTP(BaseModel):
    phone_number: str
    otp: str
