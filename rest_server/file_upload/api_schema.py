from typing import Optional

from pydantic import BaseModel


class PresignedURLRequest(BaseModel):
    bucket_name: str
    folder_path: Optional[str] = None
    file_name: str
    content_type: str


class ImageUploadNotification(BaseModel):
    url: str
    metadata: dict
