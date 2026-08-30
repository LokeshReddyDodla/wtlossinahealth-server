import logging
from datetime import datetime, timedelta

from decouple import config
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError

logger = logging.getLogger(__name__)

JWT_SECRET = config("JWT_SECRET")
JWT_ALGORITHM = config("JWT_ALGORITHM")
JWT_AUDIENCE = config("JWT_AUDIENCE")
ACCESS_TOKEN_EXPIRE_MINUTES = 30


def create_jwt_token(user_id: str, role: str):
    expire = datetime.now().replace(tzinfo=None) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )
    # "exp": expire
    token_data = {
        "sub": user_id,
        "role": role,  # Store the user type (Patient, Doctor, etc.)
        "aud": JWT_AUDIENCE,
    }
    return jwt.encode(token_data, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt_token(token: str):
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            audience=JWT_AUDIENCE,
        )
        return payload
    except ExpiredSignatureError:
        logger.warning("jwt_expired")
        return None
    except JWTError:
        logger.warning("jwt_invalid")
        return None


def verify_jwt_token(token: str) -> bool:
    try:
        jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            audience=JWT_AUDIENCE,
        )
        return True
    except ExpiredSignatureError:
        logger.warning("jwt_verify_expired")
        return False
    except JWTError:
        logger.warning("jwt_verify_invalid")
        return False
