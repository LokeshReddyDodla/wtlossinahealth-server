
from pydantic import BaseModel


class CGMDataUpload(BaseModel):
    file: bytes
    patient_id: str
    device: str
    serial_number: str
