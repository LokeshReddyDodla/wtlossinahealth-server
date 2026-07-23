"""Patient-level InBody report service: upload, extraction lifecycle and
reads.

The file goes to S3; the index row and the extracted analysis (fixed
per-scan values) live on the ``patient_inbody_reports`` Postgres row.
"""

from __future__ import annotations

import uuid as uuid_module
from datetime import date
from typing import Any, Dict, List, Optional
from uuid import UUID

from decouple import config
from fastapi import status
from loguru import logger
from sqlalchemy import select

from lib.core.postgres_store import PostgresStore
from lib.models.patient_inbody_report import PatientInbodyReport
from lib.services.inbody.extraction_service import InbodyExtractionService
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.s3_utils import upload_file_to_s3

INBODY_S3_BUCKET = config(
    "INBODY_S3_BUCKET", default="user-assets.aihealth.clinic"
)
INBODY_S3_FOLDER = "inbody-reports"

ALLOWED_CONTENT_TYPES = (
    "image/jpeg",
    "image/jpg",
    "image/png",
    "application/pdf",
)


class InbodyReportService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        extraction_service: InbodyExtractionService,
    ) -> None:
        self.postgres_store = postgres_store
        self.extraction_service = extraction_service

    # ------------------------------------------------------------------
    # Upload + extraction lifecycle
    # ------------------------------------------------------------------

    async def upload_report(
        self,
        *,
        patient_id: UUID,
        file_bytes: bytes,
        original_filename: Optional[str],
        content_type: str,
        report_date: Optional[date],
        uploaded_by_role: Optional[str],
        uploaded_by_id: Optional[UUID],
    ) -> Dict[str, Any]:
        """Store the file, index it, extract, and return the full record.

        Extraction failure does not fail the upload — the report is kept in
        ``failed`` status with the error recorded, retriable via
        :meth:`reextract_report`.
        """

        if content_type not in ALLOWED_CONTENT_TYPES:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=(
                    f"Unsupported file type {content_type}. Allowed: "
                    f"{', '.join(ALLOWED_CONTENT_TYPES)}"
                ),
            )
        if not file_bytes:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Empty file",
            )

        report_id = uuid_module.uuid4()
        extension = (original_filename or "").rsplit(".", 1)[-1].lower()
        if extension not in ("pdf", "png", "jpg", "jpeg"):
            extension = "pdf" if content_type == "application/pdf" else "jpg"

        file_url = upload_file_to_s3(
            file_bytes=file_bytes,
            bucket_name=INBODY_S3_BUCKET,
            file_name=f"{report_id}.{extension}",
            content_type=content_type,
            folder_path=f"{INBODY_S3_FOLDER}/{patient_id}",
        )
        if not file_url:
            raise_http_exception(
                status_code=status.HTTP_502_BAD_GATEWAY,
                message="Failed to store report file",
            )

        logger.info(
            "inbody: uploaded report={} patient={} file={} size={}b",
            report_id,
            patient_id,
            original_filename,
            len(file_bytes),
        )

        async with self.postgres_store.get_session() as session:
            row = PatientInbodyReport(
                report_id=report_id,
                patient_id=patient_id,
                file_url=file_url,
                original_filename=original_filename,
                content_type=content_type,
                # Fallback ordering key until extraction reads the printed
                # test date off the sheet.
                report_date=report_date or date.today(),
                status="uploaded",
                uploaded_by_role=uploaded_by_role,
                uploaded_by_id=uploaded_by_id,
            )
            session.add(row)
            await session.commit()

        await self._run_extraction(
            report_id=report_id,
            patient_id=patient_id,
            file_bytes=file_bytes,
            content_type=content_type,
            explicit_report_date=report_date,
        )

        return await self.get_report_detail(patient_id, report_id)

    async def _run_extraction(
        self,
        *,
        report_id: UUID,
        patient_id: UUID,
        file_bytes: bytes,
        content_type: str,
        explicit_report_date: Optional[date],
    ) -> None:
        await self._set_status(report_id, "extracting")

        try:
            extraction = await self.extraction_service.extract(
                file_bytes=file_bytes,
                content_type=content_type,
                report_id=str(report_id),
            )
        except Exception as exc:
            logger.error(
                "inbody: extraction failed report={} patient={}: {}",
                report_id,
                patient_id,
                exc,
            )
            await self._set_status(report_id, "failed", error=str(exc))
            return

        final_status = (
            "needs_review"
            if self.extraction_service.needs_review(extraction)
            else "extracted"
        )

        # The printed test date beats the upload-time guess; an explicitly
        # provided date beats both.
        extracted_date = None
        if not explicit_report_date and extraction.report_date:
            try:
                extracted_date = date.fromisoformat(extraction.report_date)
            except ValueError:
                pass

        await self._set_status(
            report_id,
            final_status,
            report_date=extracted_date,
            analysis=extraction.model_dump(),
        )
        logger.info(
            "inbody: report={} status={} confidence={}",
            report_id,
            final_status,
            extraction.extraction_confidence,
        )

    async def reextract_report(
        self, patient_id: UUID, report_id: UUID, file_bytes: bytes
    ) -> Dict[str, Any]:
        """Re-run extraction for a failed/needs_review report."""

        row = await self._get_row(patient_id, report_id)
        await self._run_extraction(
            report_id=report_id,
            patient_id=patient_id,
            file_bytes=file_bytes,
            content_type=row.content_type or "application/pdf",
            explicit_report_date=None,
        )
        return await self.get_report_detail(patient_id, report_id)

    async def _set_status(
        self,
        report_id: UUID,
        new_status: str,
        *,
        error: Optional[str] = None,
        report_date: Optional[date] = None,
        analysis: Optional[Dict[str, Any]] = None,
    ) -> None:
        async with self.postgres_store.get_session() as session:
            row = await session.get(PatientInbodyReport, report_id)
            if not row:
                return
            row.status = new_status
            row.error = error
            if report_date:
                row.report_date = report_date
            if analysis is not None:
                row.analysis = analysis
            await session.commit()

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def _get_row(
        self, patient_id: UUID, report_id: UUID
    ) -> PatientInbodyReport:
        async with self.postgres_store.get_session() as session:
            row = await session.get(PatientInbodyReport, report_id)
        if not row or row.patient_id != patient_id:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="InBody report not found",
            )
        return row

    @staticmethod
    def _row_to_dict(
        row: PatientInbodyReport, *, include_analysis: bool = False
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "report_id": str(row.report_id),
            "patient_id": str(row.patient_id),
            "file_url": row.file_url,
            "original_filename": row.original_filename,
            "report_date": row.report_date.isoformat()
            if row.report_date
            else None,
            "status": row.status,
            "uploaded_by_role": row.uploaded_by_role,
            "error": row.error,
            "created_at": row.created_at.isoformat()
            if row.created_at
            else None,
        }
        if include_analysis:
            data["analysis"] = row.analysis
        return data

    async def list_reports(
        self, patient_id: UUID, limit: int = 50
    ) -> List[Dict[str, Any]]:
        async with self.postgres_store.get_session() as session:
            result = await session.execute(
                select(PatientInbodyReport)
                .where(PatientInbodyReport.patient_id == patient_id)
                .order_by(PatientInbodyReport.report_date.desc())
                .limit(limit)
            )
            rows = result.scalars().all()
        return [self._row_to_dict(row) for row in rows]

    async def get_report_detail(
        self, patient_id: UUID, report_id: UUID
    ) -> Dict[str, Any]:
        row = await self._get_row(patient_id, report_id)
        return self._row_to_dict(row, include_analysis=True)

    async def get_latest_report(
        self, patient_id: UUID
    ) -> Optional[Dict[str, Any]]:
        # Latest means latest *usable* scan — failed uploads (whose
        # report_date is just the upload day) must not shadow real reports.
        async with self.postgres_store.get_session() as session:
            result = await session.execute(
                select(PatientInbodyReport)
                .where(
                    PatientInbodyReport.patient_id == patient_id,
                    PatientInbodyReport.status.in_(
                        ["extracted", "needs_review"]
                    ),
                )
                .order_by(PatientInbodyReport.report_date.desc())
                .limit(1)
            )
            row = result.scalars().first()
        if not row:
            return None
        return self._row_to_dict(row, include_analysis=True)
