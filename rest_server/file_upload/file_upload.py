from fastapi import APIRouter, status, Depends

from lib.dependencies.auth.base import get_current_user
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.s3_utils import generate_presigned_url
from rest_server.response_models import SuccessResponse

from .api_schema import PresignedURLRequest

router = APIRouter(prefix="/file_upload")


@router.post("/generate_presigned_url/", tags=["File Upload"])
def generate_presigned_url_endpoint(
    request: PresignedURLRequest, current_user=Depends(get_current_user)
):
    response = generate_presigned_url(
        request.bucket_name,
        request.file_name,
        request.content_type,
        folder_path=request.folder_path,
    )
    if response is None:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to generate pre-signed URL",
        )

    return SuccessResponse(data=response)
