from typing import Optional
import httpx
from fastapi import HTTPException
from decouple import config
from .base import OTPProvider

MSG91_BASE_URL = "https://control.msg91.com/api/v5/otp"
MSG91_AUTH_KEY = config("MSG91_AUTH_KEY")
TEMPLATE_ID = "688b21dcd6fc05294a54e8e2"


class Msg91OTPProvider(OTPProvider):
    async def send_otp(
        self, phone_number: str, otp: Optional[str] = None
    ) -> dict:
        payload = {
            "mobile": phone_number,
            "template_id": TEMPLATE_ID,
            "otp_length": "4",
        }
        headers = {"Authkey": MSG91_AUTH_KEY}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                MSG91_BASE_URL, json=payload, headers=headers  # type: ignore
            )
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to send OTP")

        return response.json()

    async def verify_otp(self, phone_number: str, otp: str) -> bool:
        params = {"mobile": phone_number, "otp": otp}
        headers = {"Authkey": MSG91_AUTH_KEY}

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{MSG91_BASE_URL}/verify", params=params, headers=headers  # type: ignore
            )

        data = response.json()
        if data.get("type") != "success":
            raise HTTPException(status_code=400, detail="Invalid OTP")

        return True

    async def retry_otp(
        self, phone_number: str, retry_type: str = "text"
    ) -> dict:
        params = {"mobile": phone_number, "retrytype": retry_type}
        headers = {"Authkey": MSG91_AUTH_KEY}

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{MSG91_BASE_URL}/retry", params=params, headers=headers  # type: ignore
            )
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail="Retry OTP failed")
        return response.json()
