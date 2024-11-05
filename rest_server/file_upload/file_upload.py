from fastapi import APIRouter, HTTPException

from lib.utils.s3_utils import generate_presigned_url
from rest_server.response_models import SuccessResponse

from .api_schema import ImageUploadNotification, PresignedURLRequest

router = APIRouter(prefix="/file_upload")


@router.post("/generate_presigned_url/", tags=["File Upload"])
def generate_presigned_url_endpoint(request: PresignedURLRequest):
    response = generate_presigned_url(
        request.bucket_name,
        request.file_name,
        request.content_type,
        folder_path=request.folder_path,
    )
    if response is None:
        raise HTTPException(
            status_code=500, detail="Failed to generate pre-signed URL"
        )
    return SuccessResponse(data=response)


@router.post("/upload_completed/", tags=["File Upload"])
def upload_completed_endpoint(notification: ImageUploadNotification):
    # Process the uploaded file URL and metadata
    # For example, store in the database
    return {"status": "success"}
