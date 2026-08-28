"""Migrate legacy InBody documents from MongoDB patient_documents into the new
body-composition pipeline (Postgres + new S3 path + vision re-extraction).

For each InBody doc: downloads image from existing S3 URL, re-uploads to the
new body-composition S3 prefix, runs vision extraction, and creates a
PatientBodyCompositionRecord via BodyCompositionService.create_draft().

Built-in dedup (content_hash + test_datetime+manufacturer) prevents double
imports if a patient was already uploaded through the new flow.

Usage:
    python scripts/migrate_inbody_to_body_composition.py --dry-run
    python scripts/migrate_inbody_to_body_composition.py --limit 5
    python scripts/migrate_inbody_to_body_composition.py
    docker compose exec api python scripts/migrate_inbody_to_body_composition.py
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import sys
from pathlib import Path
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.core.container import container  # noqa: E402
from lib.core.mongo_store import MongoStore  # noqa: E402
from lib.schemas.body_composition import IngestChannel  # noqa: E402
from lib.services.body_composition.extraction import BodyCompositionExtractionService  # noqa: E402
from lib.services.body_composition.service import BodyCompositionService  # noqa: E402
from lib.utils.s3_utils import s3_client, upload_file_to_s3  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger("migrate_inbody")

COLLECTION = "patient_documents"
S3_BUCKET = "user-assets.aihealth.clinic"
INBODY_QUERY = {
    "$or": [
        {"file.name": {"$regex": "InBody", "$options": "i"}},
        {"text_raw": {"$regex": "^InBody"}},
    ]
}
PROJECTION = {
    "_id": 1,
    "patient_id": 1,
    "file": 1,
    "metadata": 1,
}

CONTENT_TYPE_MAP = {
    "image/jpeg": "image/jpeg",
    "image/jpg": "image/jpeg",
    "image/png": "image/png",
    "application/pdf": "application/pdf",
}


def download_from_s3(url: str) -> bytes | None:
    prefix = f"https://{S3_BUCKET}/"
    if not url.startswith(prefix):
        logger.warning("unexpected URL format: %s", url)
        return None
    key = url[len(prefix):]
    try:
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
        return resp["Body"].read()
    except Exception as e:
        logger.warning("S3 download failed %s: %s", key, e)
        return None


async def run(dry_run: bool, limit: int | None) -> None:
    mongo = MongoStore()
    collection = mongo.get_collection(COLLECTION)
    extraction_service = container.resolve(BodyCompositionExtractionService)
    bc_service = container.resolve(BodyCompositionService)

    cursor = collection.find(INBODY_QUERY, PROJECTION).sort("_id", 1)
    if limit:
        cursor = cursor.limit(limit)
    docs = await cursor.to_list(length=limit or 500)

    total = len(docs)
    logger.info("Found %d InBody documents to migrate", total)

    created = 0
    duplicates = 0
    failed = 0
    skipped = 0

    for i, doc in enumerate(docs, start=1):
        mongo_id = doc["_id"]
        patient_id_str = doc.get("patient_id")
        file_info = doc.get("file") or {}
        file_url = file_info.get("url")
        file_name = file_info.get("name", "")
        content_type = CONTENT_TYPE_MAP.get(file_info.get("type", ""), "image/jpeg")
        metadata = doc.get("metadata") or {}
        uploaded_by = metadata.get("uploaded_by") or {}

        if not patient_id_str or not file_url:
            logger.warning("[%d/%d] %s: missing patient_id or file URL, skipping", i, total, mongo_id)
            skipped += 1
            continue

        try:
            patient_id = UUID(patient_id_str)
        except ValueError:
            logger.warning("[%d/%d] %s: invalid patient_id %s", i, total, mongo_id, patient_id_str)
            skipped += 1
            continue

        if dry_run:
            logger.info("[%d/%d] DRY-RUN %s patient=%s file=%s", i, total, mongo_id, patient_id_str, file_name)
            continue

        file_bytes = download_from_s3(file_url)
        if not file_bytes:
            logger.warning("[%d/%d] %s: download failed", i, total, mongo_id)
            failed += 1
            continue

        content_hash = hashlib.sha256(file_bytes).hexdigest()

        ext = Path(file_name).suffix.lower() if file_name else ".jpg"
        if ext not in {".pdf", ".jpg", ".jpeg", ".png"}:
            ext = ".jpg"
        new_s3_url = upload_file_to_s3(
            file_bytes=file_bytes,
            bucket_name=S3_BUCKET,
            file_name=f"{uuid4().hex}{ext}",
            content_type=content_type,
            folder_path=f"patients/{patient_id}/documents/body-composition",
        )
        if not new_s3_url:
            logger.warning("[%d/%d] %s: S3 re-upload failed", i, total, mongo_id)
            failed += 1
            continue

        try:
            extracted = await extraction_service.extract(
                file_bytes=file_bytes,
                content_type=content_type,
                patient_id=str(patient_id),
            )
        except Exception as e:
            logger.warning("[%d/%d] %s: extraction failed: %s", i, total, mongo_id, e)
            failed += 1
            continue

        uploader_id = None
        uploader_type = uploaded_by.get("type", "care_provider")
        if uploaded_by.get("id"):
            try:
                uploader_id = UUID(uploaded_by["id"])
            except ValueError:
                pass

        try:
            record = await bc_service.create_draft(
                patient_id=patient_id,
                data=extracted,
                ingest_channel=IngestChannel.MIGRATION,
                source_file_url=new_s3_url,
                original_filename=file_name,
                content_type=content_type,
                uploaded_by_id=uploader_id,
                uploaded_by_type=uploader_type,
                content_hash=content_hash,
            )
        except Exception as e:
            logger.warning("[%d/%d] %s: create_draft failed: %s", i, total, mongo_id, e)
            failed += 1
            continue

        if record.get("duplicate"):
            duplicates += 1
            logger.info("[%d/%d] %s: duplicate, skipped", i, total, mongo_id)
        else:
            created += 1
            logger.info(
                "[%d/%d] %s: created record=%s status=%s confidence=%.2f",
                i, total, mongo_id,
                record["record_id"], record["status"],
                record.get("extraction_confidence", 0),
            )

        if i % 20 == 0:
            logger.info(
                "  progress: %d/%d (created=%d, dup=%d, failed=%d, skipped=%d)",
                i, total, created, duplicates, failed, skipped,
            )

    logger.info("--- Done ---")
    logger.info("  total:      %d", total)
    logger.info("  created:    %d", created)
    logger.info("  duplicates: %d", duplicates)
    logger.info("  failed:     %d", failed)
    logger.info("  skipped:    %d", skipped)
    if dry_run:
        logger.info("Dry-run mode - no records were created.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run, limit=args.limit))


if __name__ == "__main__":
    main()
