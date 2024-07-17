from pydantic import BaseModel
from typing import Optional


class CGMDataUpload(BaseModel):
    file: bytes
    patient_id: str
    device: str
    serial_number: str
