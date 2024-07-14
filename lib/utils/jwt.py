from jose import jwt
from jose.exceptions import JWTError, ExpiredSignatureError
from decouple import config
from lib.models.user import User

JWT_SECRET = config("JWT_SECRET")
JWT_ALGORITHM = config("JWT_ALGORITHM")
JWT_AUDIENCE = config("JWT_AUDIENCE")

def create_jwt_token(user: User):
    token_data = {
        "sub": str(user.user_id),
        "phone_number": user.phone_number,
        "aud": JWT_AUDIENCE
    }
    return jwt.encode(token_data, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt_token(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM], audience=JWT_AUDIENCE)
        return payload
    except ExpiredSignatureError:
        return None
    except JWTError:
        return None