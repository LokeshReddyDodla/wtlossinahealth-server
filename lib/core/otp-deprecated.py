import random
import string
from fastapi import HTTPException
import httpx
from loguru import logger
from lib.core.cache_store import CacheStore
from decouple import config

OTP_EXPIRY_TIME = 300  # 5 minutes in seconds

MSG91_BASE_URL = "https://control.msg91.com/api/v5/otp"
MSG91_AUTH_KEY = config("MSG91_AUTH_KEY")
TEMPLATE_ID = "688b21dcd6fc05294a54e8e2"


def generate_otp(length=6):
    return "".join(random.choices(string.digits, k=length))


async def send_otp_backend(phone_number: str):
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

    data = response.json()
    print("==> send_otp_backend: ", data)
    return data


async def verify_otp_backend(phone_number: str, otp: str):
    params = {"mobile": phone_number, "otp": otp}
    headers = {"Authkey": MSG91_AUTH_KEY}

    async with httpx.AsyncClient() as client:
        response = await client.get(f"{MSG91_BASE_URL}/verify", params=params, headers=headers)  # type: ignore

    data = response.json()
    print("==> verify_otp_backend: ", data)

    if data.get("type") != "success":
        raise HTTPException(status_code=400, detail="Invalid OTP")

    return True


async def retry_otp_backend(phone_number: str, retry_type: str = "text"):
    params = {"mobile": phone_number, "retrytype": retry_type}
    headers = {"Authkey": MSG91_AUTH_KEY}

    async with httpx.AsyncClient() as client:
        response = await client.get(f"{MSG91_BASE_URL}/retry", params=params, headers=headers)  # type: ignore

    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="Retry OTP failed")
    return response.json()


async def create_and_send_otp(phone_number: str, cache_store: CacheStore):
    otp = generate_otp(length=4)
    cache_store.set_key(phone_number, otp, OTP_EXPIRY_TIME)
    # Simulate sending OTP via SMS
    logger.info(f"Sending OTP {otp} to {phone_number}")


async def verify_otp(
    phone_number: str, otp: str, cache_store: CacheStore
) -> bool:
    stored_otp = cache_store.get_key(phone_number)
    if stored_otp and stored_otp.decode() == otp:
        cache_store.delete_key(phone_number)
        return True
    # return False
    return True  # bypassing otp verification
