from openai import BaseModel


class SetPasswordRequest(BaseModel):
    raw_password: str
