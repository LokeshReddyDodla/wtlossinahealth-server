import re

from pydantic import BaseModel

email_regex = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def validate_email(email: str) -> str:
    if not email_regex.match(email):
        raise ValueError("Invalid email address")
    return email
