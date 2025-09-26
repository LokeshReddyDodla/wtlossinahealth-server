from typing import Optional

import boto3
from botocore.exceptions import ClientError
from decouple import config

s3_client = boto3.client(
    "s3",
    aws_access_key_id=config("AWS_S3_ACCESS_KEY"),
    aws_secret_access_key=config("AWS_S3_SECRET_KEY"),
    region_name="ap-south-1",
)


def generate_presigned_url(
    bucket_name: str,
    file_name: str,
    content_type: str,
    expiration: int = 3600,
    folder_path: Optional[str] = None,
) -> Optional[dict]:
    """Generate a pre-signed URL for S3 bucket."""

    object_name = f"{folder_path}/{file_name}" if folder_path else file_name

    try:
        response = s3_client.generate_presigned_post(
            bucket_name,
            object_name,
            Fields={"Content-Type": content_type},
            Conditions=[{"Content-Type": content_type}],
            ExpiresIn=expiration,
        )
        return response
    except ClientError as e:
        print(f"ClientError: {e}")
        return None


def upload_file_to_s3(
    file_bytes: bytes,
    bucket_name: str,
    file_name: str,
    content_type: str,
    folder_path: Optional[str] = None,
) -> Optional[str]:
    """Upload a file to an S3 bucket."""

    object_name = f"{folder_path}/{file_name}" if folder_path else file_name

    try:
        s3_client.put_object(
            Bucket=bucket_name,
            Key=object_name,
            Body=file_bytes,
            ContentType=content_type,
        )
        file_url = f"https://{bucket_name}/{object_name}"
        return file_url
    except ClientError as e:
        print(f"ClientError: {e}")
        return None
