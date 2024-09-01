import random
import string
from loguru import logger
from lib.core.cache_store import CacheStore

OTP_EXPIRY_TIME = 300  # 5 minutes in seconds


def generate_otp(length=6):
    return "".join(random.choices(string.digits, k=length))


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
    return False
