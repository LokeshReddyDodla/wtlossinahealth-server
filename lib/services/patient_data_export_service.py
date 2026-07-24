from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

from bson import ObjectId
from decouple import config
from loguru import logger
from sqlalchemy import String, and_, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.constants import ProfileTypeEnum
from lib.core.mongo_store import MongoStore
from lib.core.postgres_store import PostgresStore
from lib.models import Base
from lib.models.patient import Patient
from lib.models.patient_data_export import PatientDataExport
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session
from lib.utils.s3_utils import (
    generate_presigned_download_url,
    upload_local_file_to_s3,
)


class PatientDataExportService:
    MAX_CHUNK_BYTES = 25 * 1024 * 1024
    DOWNLOAD_URL_TTL_SECONDS = 15 * 60
    EXPORT_TTL_DAYS = 7
    REQUEST_COOLDOWN_SECONDS = int(
        config("PATIENT_EXPORT_REQUEST_COOLDOWN_SECONDS", default=300)
    )

    CLICKHOUSE_TABLES = [
        "aihealth.cgm_data",
        "aihealth.fitness_data",
        "aihealth.sleep_data",
    ]

    MONGO_PATIENT_ID_COLLECTIONS = [
        "cgm_reports",
        "fitness_reports",
        "sleep_reports",
        "meal_reports",
        "patient_summaries",
        "patient_documents",
        "patient_document_summary_interactions",
        "profile_update_conversations",
    ]

    MONGO_USER_ID_COLLECTIONS: list[str] = []

    def __init__(self, postgres_store: PostgresStore, mongo_store: MongoStore, clickhouse_store):
        self.postgres_store = postgres_store
        self.mongo_store = mongo_store
        self.clickhouse_store = clickhouse_store
        self.s3_bucket = config("PATIENT_EXPORTS_BUCKET", default="user-assets.aihealth.clinic")

    @with_postgres_session
    async def create_export(
        self,
        patient_id: UUID,
        requester_id: UUID,
        requester_role: ProfileTypeEnum,
        *,
        postgres_session: AsyncSession,
    ) -> PatientDataExport:
        now = datetime.now().replace(tzinfo=None)

        patient = await postgres_session.scalar(
            select(Patient).where(Patient.patient_id == patient_id)
        )
        if not patient:
            raise_http_exception(status_code=404, message="Patient not found")

        active_export = await postgres_session.scalar(
            select(PatientDataExport)
            .where(
                PatientDataExport.patient_id == patient_id,
                PatientDataExport.status.in_(["queued", "running"]),
            )
            .order_by(PatientDataExport.created_at.desc())
        )
        if active_export:
            raise_http_exception(
                status_code=429,
                message="An export is already in progress for this patient",
                detail=f"active_export_id={active_export.export_id}",
            )

        cooldown_cutoff = now - timedelta(seconds=self.REQUEST_COOLDOWN_SECONDS)
        recent_export = await postgres_session.scalar(
            select(PatientDataExport)
            .where(
                PatientDataExport.patient_id == patient_id,
                PatientDataExport.requester_id == requester_id,
                PatientDataExport.created_at >= cooldown_cutoff,
            )
            .order_by(PatientDataExport.created_at.desc())
        )
        if recent_export:
            elapsed = int((now - recent_export.created_at).total_seconds())
            retry_after = max(0, self.REQUEST_COOLDOWN_SECONDS - elapsed)
            raise_http_exception(
                status_code=429,
                message="Too many export requests. Please try again later.",
                detail=(
                    f"retry_after_seconds={retry_after}; "
                    f"last_export_id={recent_export.export_id}"
                ),
            )

        export = PatientDataExport(
            patient_id=patient_id,
            requester_id=requester_id,
            requester_role=requester_role.value,
            status="queued",
            progress=0,
            expires_at=now + timedelta(days=self.EXPORT_TTL_DAYS),
        )
        postgres_session.add(export)
        await postgres_session.commit()
        await postgres_session.refresh(export)
        return export

    @with_postgres_session
    async def get_export_by_id(
        self, export_id: UUID, *, postgres_session: AsyncSession
    ) -> Optional[PatientDataExport]:
        return await postgres_session.scalar(
            select(PatientDataExport).where(PatientDataExport.export_id == export_id)
        )

    @with_postgres_session
    async def mark_downloaded(
        self, export_id: UUID, *, postgres_session: AsyncSession
    ) -> None:
        export = await postgres_session.scalar(
            select(PatientDataExport).where(PatientDataExport.export_id == export_id)
        )
        if not export:
            return
        export.last_downloaded_at = datetime.now().replace(tzinfo=None)
        await postgres_session.commit()

    @with_postgres_session
    async def list_exports(
        self,
        *,
        patient_id: Optional[UUID] = None,
        statuses: Optional[List[str]] = None,
        requester_id: Optional[UUID] = None,
        limit: int = 20,
        offset: int = 0,
        postgres_session: AsyncSession,
    ) -> List[PatientDataExport]:
        stmt = select(PatientDataExport)

        filters = []
        if patient_id:
            filters.append(PatientDataExport.patient_id == patient_id)
        if statuses:
            filters.append(PatientDataExport.status.in_(statuses))
        if requester_id:
            filters.append(PatientDataExport.requester_id == requester_id)
        if filters:
            stmt = stmt.where(and_(*filters))

        stmt = (
            stmt.order_by(PatientDataExport.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await postgres_session.execute(stmt)
        return list(result.scalars().all())

    @with_postgres_session
    async def count_exports(
        self,
        *,
        patient_id: Optional[UUID] = None,
        statuses: Optional[List[str]] = None,
        requester_id: Optional[UUID] = None,
        postgres_session: AsyncSession,
    ) -> int:
        stmt = select(func.count(PatientDataExport.export_id))

        filters = []
        if patient_id:
            filters.append(PatientDataExport.patient_id == patient_id)
        if statuses:
            filters.append(PatientDataExport.status.in_(statuses))
        if requester_id:
            filters.append(PatientDataExport.requester_id == requester_id)
        if filters:
            stmt = stmt.where(and_(*filters))

        result = await postgres_session.execute(stmt)
        return int(result.scalar() or 0)

    async def generate_download_url(self, export: PatientDataExport) -> Optional[str]:
        if not export.s3_object_key:
            return None

        return generate_presigned_download_url(
            bucket_name=self.s3_bucket,
            object_key=export.s3_object_key,
            expiration=self.DOWNLOAD_URL_TTL_SECONDS,
        )

    @with_postgres_session
    async def mark_expired(
        self, export_id: UUID, *, postgres_session: AsyncSession
    ) -> None:
        export = await postgres_session.scalar(
            select(PatientDataExport).where(PatientDataExport.export_id == export_id)
        )
        if not export:
            return

        export.status = "expired"
        export.error = None
        await postgres_session.commit()

    async def process_export_job(self, export_id: str) -> Dict[str, Any]:
        export_uuid = UUID(export_id)
        temp_root: Optional[str] = None

        async with self.postgres_store.get_session() as session:
            export = await session.scalar(
                select(PatientDataExport).where(PatientDataExport.export_id == export_uuid)
            )
            if not export:
                return {"success": False, "error": "Export job not found"}

            if export.status in {"completed", "running"}:
                return {
                    "success": True,
                    "status": export.status,
                    "export_id": str(export.export_id),
                }

            export.status = "running"
            export.progress = 5
            export.error = None
            await session.commit()

        try:
            patient_uuid = export.patient_id
            patient_id = str(patient_uuid)
            temp_root = tempfile.mkdtemp(prefix=f"patient_export_{export_id}_")
            data_root = Path(temp_root) / "data"
            data_root.mkdir(parents=True, exist_ok=True)

            manifest: Dict[str, Any] = {
                "schema_version": "2026.03",
                "export_id": export_id,
                "patient_id": patient_id,
                "created_at": datetime.now().replace(tzinfo=None).isoformat(),
                "sources": {},
            }

            postgres_data = await self._extract_postgres_data(patient_uuid)
            manifest["sources"]["postgres"] = self._write_source_chunks(
                source="postgres",
                source_data=postgres_data,
                base_dir=data_root,
            )
            await self._update_progress(export_uuid, 35)

            mongo_data = await self._extract_mongo_data(patient_id)
            manifest["sources"]["mongo"] = self._write_source_chunks(
                source="mongo",
                source_data=mongo_data,
                base_dir=data_root,
            )
            await self._update_progress(export_uuid, 65)

            clickhouse_data = self._extract_clickhouse_data(patient_id)
            manifest["sources"]["clickhouse"] = self._write_source_chunks(
                source="clickhouse",
                source_data=clickhouse_data,
                base_dir=data_root,
            )
            await self._update_progress(export_uuid, 85)

            manifest_path = Path(temp_root) / "manifest.json"
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)

            zip_path = Path(temp_root) / f"{export_id}.zip"
            self._create_zip_archive(
                zip_path=zip_path,
                root_dir=Path(temp_root),
                include_paths=["manifest.json", "data"],
            )
            checksum = self._sha256_file(zip_path)
            object_key = f"patient-exports/{patient_id}/{export_id}.zip"

            uploaded_key = upload_local_file_to_s3(
                local_path=str(zip_path),
                bucket_name=self.s3_bucket,
                object_key=object_key,
            )
            if not uploaded_key:
                raise RuntimeError("Failed to upload export archive to S3")

            async with self.postgres_store.get_session() as session:
                export = await session.scalar(
                    select(PatientDataExport).where(
                        PatientDataExport.export_id == export_uuid
                    )
                )
                if not export:
                    raise RuntimeError("Export row missing during finalize")

                export.status = "completed"
                export.progress = 100
                export.manifest = manifest
                export.s3_object_key = uploaded_key
                export.checksum = checksum
                export.completed_at = datetime.now().replace(tzinfo=None)
                export.error = None
                await session.commit()

            return {
                "success": True,
                "export_id": export_id,
                "object_key": uploaded_key,
                "checksum": checksum,
            }

        except Exception as error:
            logger.exception("Patient export failed for %s: %s", export_id, error)
            async with self.postgres_store.get_session() as session:
                export = await session.scalar(
                    select(PatientDataExport).where(
                        PatientDataExport.export_id == export_uuid
                    )
                )
                if export:
                    export.status = "failed"
                    export.error = str(error)
                    export.progress = 100
                    await session.commit()

            return {"success": False, "export_id": export_id, "error": str(error)}

        finally:
            if temp_root and os.path.exists(temp_root):
                shutil.rmtree(temp_root, ignore_errors=True)

    async def expire_old_exports(self) -> Dict[str, int]:
        now = datetime.now().replace(tzinfo=None)
        updated = 0
        deleted_objects = 0

        from lib.utils.s3_utils import s3_client

        async with self.postgres_store.get_session() as session:
            result = await session.execute(
                select(PatientDataExport).where(
                    PatientDataExport.status == "completed",
                    PatientDataExport.expires_at.isnot(None),
                    PatientDataExport.expires_at < now,
                )
            )
            exports = list(result.scalars().all())

            for export in exports:
                if export.s3_object_key:
                    try:
                        s3_client.delete_object(
                            Bucket=self.s3_bucket,
                            Key=export.s3_object_key,
                        )
                        deleted_objects += 1
                    except Exception as delete_error:
                        logger.warning(
                            "Failed deleting expired export object %s: %s",
                            export.s3_object_key,
                            delete_error,
                        )

                export.status = "expired"
                export.error = None
                updated += 1

            if updated:
                await session.commit()

        return {"expired_exports": updated, "deleted_objects": deleted_objects}

    async def _update_progress(self, export_id: UUID, progress: int) -> None:
        async with self.postgres_store.get_session() as session:
            export = await session.scalar(
                select(PatientDataExport).where(PatientDataExport.export_id == export_id)
            )
            if not export:
                return
            export.progress = progress
            await session.commit()

    async def _extract_postgres_data(self, patient_id: UUID) -> Dict[str, List[Dict[str, Any]]]:
        data: Dict[str, List[Dict[str, Any]]] = {}

        async with self.postgres_store.get_session() as session:
            for table in sorted(Base.metadata.tables.values(), key=lambda t: t.name):
                if "patient_id" in table.columns:
                    rows = await self._fetch_rows(session, table, table.c.patient_id == patient_id)
                    if rows:
                        data[table.name] = rows

            # patient scoped user logs
            user_device_table = Base.metadata.tables.get("user_devices")
            if user_device_table is not None:
                rows = await self._fetch_rows(
                    session,
                    user_device_table,
                    (user_device_table.c.user_id == patient_id)
                    & (cast(user_device_table.c.profile_type, String) == ProfileTypeEnum.PATIENT.value),
                )
                if rows:
                    data[user_device_table.name] = rows

            user_activity_table = Base.metadata.tables.get("user_activity_logs")
            if user_activity_table is not None:
                rows = await self._fetch_rows(
                    session,
                    user_activity_table,
                    (user_activity_table.c.user_id == patient_id)
                    & (cast(user_activity_table.c.profile_type, String) == ProfileTypeEnum.PATIENT.value),
                )
                if rows:
                    data[user_activity_table.name] = rows

            token_usage_table = Base.metadata.tables.get("token_usage_logs")
            if token_usage_table is not None:
                rows = await self._fetch_rows(
                    session,
                    token_usage_table,
                    (token_usage_table.c.user_id == patient_id)
                    & (
                        cast(token_usage_table.c.user_type, String).in_(
                            ["PATIENT", "patient"]
                        )
                    ),
                )
                if rows:
                    data[token_usage_table.name] = rows

            # children of patient_meals
            meal_rows = data.get("patient_meals", [])
            meal_ids = [row.get("id") for row in meal_rows if row.get("id")]
            if meal_ids:
                food_items_table = Base.metadata.tables.get("patient_food_items")
                if food_items_table is not None:
                    food_rows = await self._fetch_rows(
                        session,
                        food_items_table,
                        food_items_table.c.meal_id.in_(meal_ids),
                    )
                    if food_rows:
                        data[food_items_table.name] = food_rows

                    food_item_ids = [row.get("id") for row in food_rows if row.get("id")]
                    if food_item_ids:
                        for child_name in [
                            "patient_macro_nutritional_values",
                            "patient_micro_nutritional_values",
                        ]:
                            child_table = Base.metadata.tables.get(child_name)
                            if child_table is None:
                                continue
                            child_rows = await self._fetch_rows(
                                session,
                                child_table,
                                child_table.c.food_item_id.in_(food_item_ids),
                            )
                            if child_rows:
                                data[child_name] = child_rows

                for child_name in [
                    "patient_total_macro_nutritional_values",
                    "patient_total_micro_nutritional_values",
                ]:
                    child_table = Base.metadata.tables.get(child_name)
                    if child_table is None:
                        continue
                    child_rows = await self._fetch_rows(
                        session,
                        child_table,
                        child_table.c.meal_id.in_(meal_ids),
                    )
                    if child_rows:
                        data[child_name] = child_rows

            # children of connected apps
            connected_rows = data.get("patient_connected_apps", [])
            connected_ids = [row.get("id") for row in connected_rows if row.get("id")]
            if connected_ids:
                for child_name in ["patient_libreview", "patient_sinocare", "patient_other_apps"]:
                    child_table = Base.metadata.tables.get(child_name)
                    if child_table is None:
                        continue
                    child_rows = await self._fetch_rows(
                        session,
                        child_table,
                        child_table.c.connected_app_id.in_(connected_ids),
                    )
                    if child_rows:
                        data[child_name] = child_rows

            # children of prescriptions
            prescription_rows = data.get("patient_prescriptions", [])
            prescription_ids = [
                row.get("prescription_id")
                for row in prescription_rows
                if row.get("prescription_id")
            ]
            if prescription_ids:
                meds_table = Base.metadata.tables.get("patient_medications")
                if meds_table is not None:
                    meds_rows = await self._fetch_rows(
                        session,
                        meds_table,
                        meds_table.c.prescription_id.in_(prescription_ids),
                    )
                    if meds_rows:
                        data[meds_table.name] = meds_rows

        return data

    async def _extract_mongo_data(self, patient_id: str) -> Dict[str, List[Dict[str, Any]]]:
        out: Dict[str, List[Dict[str, Any]]] = {}

        for collection_name in self.MONGO_PATIENT_ID_COLLECTIONS:
            docs = await self._fetch_mongo_documents(collection_name, {"patient_id": patient_id})
            if docs:
                out[collection_name] = docs

        for collection_name in self.MONGO_USER_ID_COLLECTIONS:
            docs = await self._fetch_mongo_documents(collection_name, {"user_id": patient_id})
            if docs:
                out[collection_name] = docs

        chats = await self._fetch_mongo_documents("chats", {"participants.id": patient_id})
        if chats:
            out["chats"] = chats

            chat_ids = [doc.get("_id") for doc in chats if doc.get("_id")]
            msg_query: Dict[str, Any] = {"sender_id": patient_id}
            if chat_ids:
                msg_query = {
                    "$or": [
                        {"chat_id": {"$in": chat_ids}},
                        {"sender_id": patient_id},
                    ]
                }
            chat_messages = await self._fetch_mongo_documents("chat_messages", msg_query)
            if chat_messages:
                out["chat_messages"] = chat_messages

        return out

    def _extract_clickhouse_data(self, patient_id: str) -> Dict[str, List[Dict[str, Any]]]:
        output: Dict[str, List[Dict[str, Any]]] = {}
        for table in self.CLICKHOUSE_TABLES:
            query = f"SELECT * FROM {table} FINAL WHERE patient_id = %(patient_id)s"
            rows, columns = self.clickhouse_store.client.execute(
                query,
                {"patient_id": patient_id},
                with_column_types=True,
            )
            if not rows:
                continue
            column_names = [name for name, _ in columns]
            output[table] = [
                {column_names[idx]: self._json_safe(value) for idx, value in enumerate(row)}
                for row in rows
            ]
        return output

    async def _fetch_rows(self, session: AsyncSession, table, where_clause) -> List[Dict[str, Any]]:
        result = await session.execute(select(table).where(where_clause))
        return [self._serialize_mapping(dict(row)) for row in result.mappings().all()]

    async def _fetch_mongo_documents(self, collection_name: str, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        collection = self.mongo_store.get_collection(collection_name)
        cursor = collection.find(query)
        docs = await cursor.to_list(length=None)
        return [self._serialize_mapping(doc) for doc in docs]

    def _write_source_chunks(
        self,
        source: str,
        source_data: Dict[str, List[Dict[str, Any]]],
        base_dir: Path,
    ) -> Dict[str, Any]:
        source_manifest: Dict[str, Any] = {}
        source_root = base_dir / source
        source_root.mkdir(parents=True, exist_ok=True)

        for dataset, rows in source_data.items():
            chunks = self._write_dataset_chunks(
                dataset=dataset,
                rows=rows,
                dataset_dir=source_root,
            )
            source_manifest[dataset] = {
                "total_rows": len(rows),
                "chunks": chunks,
            }

        return source_manifest

    def _write_dataset_chunks(
        self,
        dataset: str,
        rows: List[Dict[str, Any]],
        dataset_dir: Path,
    ) -> List[Dict[str, Any]]:
        safe_dataset = dataset.replace(".", "_")
        out_dir = dataset_dir / safe_dataset
        out_dir.mkdir(parents=True, exist_ok=True)

        chunks: List[Dict[str, Any]] = []
        if not rows:
            return chunks

        chunk_idx = 1
        current_size = 0
        current_rows = 0
        current_file = out_dir / f"chunk_{chunk_idx:04d}.ndjson"
        handle = open(current_file, "wb")

        def flush_chunk(file_path: Path, row_count: int, size_bytes: int):
            if row_count == 0:
                return
            chunks.append(
                {
                    "path": str(file_path.relative_to(dataset_dir.parent)),
                    "rows": row_count,
                    "size_bytes": size_bytes,
                    "sha256": self._sha256_file(file_path),
                }
            )

        try:
            for row in rows:
                line = (json.dumps(self._serialize_mapping(row), ensure_ascii=False) + "\n").encode("utf-8")
                if current_size + len(line) > self.MAX_CHUNK_BYTES and current_rows > 0:
                    handle.close()
                    flush_chunk(current_file, current_rows, current_size)

                    chunk_idx += 1
                    current_file = out_dir / f"chunk_{chunk_idx:04d}.ndjson"
                    handle = open(current_file, "wb")
                    current_size = 0
                    current_rows = 0

                handle.write(line)
                current_size += len(line)
                current_rows += 1

            handle.close()
            flush_chunk(current_file, current_rows, current_size)
        finally:
            if not handle.closed:
                handle.close()

        return chunks

    def _create_zip_archive(self, zip_path: Path, root_dir: Path, include_paths: List[str]) -> None:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for include_path in include_paths:
                abs_path = root_dir / include_path
                if abs_path.is_file():
                    zf.write(abs_path, arcname=include_path)
                elif abs_path.is_dir():
                    for child in abs_path.rglob("*"):
                        if child.is_file():
                            zf.write(child, arcname=str(child.relative_to(root_dir)))

    def _sha256_file(self, file_path: Path) -> str:
        digest = hashlib.sha256()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    def _serialize_mapping(self, item: Dict[str, Any]) -> Dict[str, Any]:
        return {key: self._json_safe(value) for key, value in item.items()}

    def _json_safe(self, value: Any) -> Any:
        if value is None:
            return None

        if isinstance(value, (str, int, float, bool)):
            return value

        if isinstance(value, Decimal):
            return float(value)

        if isinstance(value, UUID):
            return str(value)

        if isinstance(value, (datetime, date)):
            return value.isoformat()

        if isinstance(value, Enum):
            return value.value

        if isinstance(value, ObjectId):
            return str(value)

        if isinstance(value, bytes):
            return value.hex()

        if isinstance(value, list):
            return [self._json_safe(v) for v in value]

        if isinstance(value, tuple):
            return [self._json_safe(v) for v in value]

        if isinstance(value, dict):
            return {str(k): self._json_safe(v) for k, v in value.items()}

        return str(value)
