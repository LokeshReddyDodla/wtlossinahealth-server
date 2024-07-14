from pydantic import BaseModel
from rest_server.response_models import SuccessResponse

class OTPRequest(BaseModel):
    phone_number: str

class OTPVerifyRequest(BaseModel):
    phone_number: str
    otp: str
