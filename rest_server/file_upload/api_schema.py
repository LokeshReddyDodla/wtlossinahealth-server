from pydantic import BaseModel

class PresignedURLRequest(BaseModel):
    bucket_name: str
    filename: str
    content_type: str

class ImageUploadNotification(BaseModel):
    url: str
    metadata: dict
