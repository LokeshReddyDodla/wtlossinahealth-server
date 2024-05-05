import boto3
from botocore.exceptions import ClientError
from typing import Optional
from decouple import config


s3_client = boto3.client(
    's3',
    aws_access_key_id=config('AWS_S3_ACCESS_KEY'),
    aws_secret_access_key=config('AWS_S3_SECRET_KEY'),
    region_name="ap-south-1"
)

def generate_presigned_url(bucket_name: str, object_name: str, content_type: str, expiration: int = 3600) -> Optional[dict]:
    """Generate a pre-signed URL for S3 bucket."""
    try:
        response = s3_client.generate_presigned_post(
            bucket_name,
            object_name,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type}
            ],
            ExpiresIn=expiration,
        )
        return response
    except ClientError as e:
        print(f"ClientError: {e}")
        return None
