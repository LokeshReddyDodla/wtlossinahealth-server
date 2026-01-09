import random
import string
from typing import Final

def generate_otp(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))

DEFAULT_OTP_LENGTH: Final[int] = 6
MIN_OTP_LENGTH: Final[int] = 4
MAX_OTP_LENGTH: Final[int] = 10
