"""
Upload the dashboard help-videos to S3 under the help-videos/ prefix.

Usage:
    python scripts/upload_help_videos.py /path/to/local/videos

Each <id>.mp4 (id must be in VIDEO_CATALOG) is uploaded to:
    s3://user-assets.aihealth.clinic/help-videos/<id>.mp4
and becomes available at:
    https://user-assets.aihealth.clinic/help-videos/<id>.mp4

Requires AWS_S3_ACCESS_KEY / AWS_S3_SECRET_KEY in the environment (same as the app).
"""

from __future__ import annotations

import pathlib
import sys

import boto3
from decouple import config

from lib.ai_foundation.agents.dashboard_help.video_catalog import (
    HELP_VIDEOS_PREFIX,
    HELP_VIDEOS_S3_BUCKET,
    VIDEO_CATALOG,
)


def main(local_dir: str) -> None:
    s3 = boto3.client(
        "s3",
        aws_access_key_id=config("AWS_S3_ACCESS_KEY"),
        aws_secret_access_key=config("AWS_S3_SECRET_KEY"),
        region_name="ap-south-1",
    )
    base = pathlib.Path(local_dir).expanduser()
    uploaded, missing = [], []

    for vid in VIDEO_CATALOG:
        path = base / f"{vid}.mp4"
        if not path.is_file():
            missing.append(vid)
            continue
        key = f"{HELP_VIDEOS_PREFIX}/{vid}.mp4"
        s3.upload_file(
            str(path),
            HELP_VIDEOS_S3_BUCKET,
            key,
            ExtraArgs={"ContentType": "video/mp4"},
        )
        print(f"  uploaded  {key}")
        uploaded.append(vid)

    print(f"\n{len(uploaded)} uploaded to s3://{HELP_VIDEOS_S3_BUCKET}/{HELP_VIDEOS_PREFIX}/")
    if missing:
        print(f"NOT FOUND locally ({len(missing)}): {', '.join(missing)}")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "videos"
    main(target)
