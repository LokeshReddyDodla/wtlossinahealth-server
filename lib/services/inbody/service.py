"""Patient-level InBody report service: upload, extraction lifecycle,
listing and cross-report trends.

Storage split: the file goes to S3 with its index row in Postgres
(``patient_inbody_reports``); the extracted analysis document lives in
MongoDB keyed by ``report_id``.
"""

from __future__ import annotations

import uuid as uuid_module
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from decouple import config
from fastapi import status
from loguru import logger
from motor.motor_asyncio import AsyncIOMotorCollection
from sqlalchemy import select

from lib.core.postgres_store import PostgresStore
from lib.models.patient_inbody_report import PatientInbodyReport
from lib.schemas.inbody import (
    InbodyExtraction,
    InbodyReportDetail,
    InbodyReportRecord,
    InbodyTrend,
    InbodyTrendsResponse,
    TrendPoint,
)
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

# Metrics surfaced by the trends endpoint, in display order.
TREND_METRICS = (
    "weight",
    "skeletal_muscle_mass",
    "body_fat_mass",
    "percent_body_fat",
    "bmi",
    "visceral_fat_level",
    "basal_metabolic_rate",
    "ecw_ratio",
)


class InbodyReportService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        analyses_collection: AsyncIOMotorCollection,
        extraction_service: InbodyExtractionService,
    ) -> None:
        self.postgres_store = postgres_store
        self.analyses_collection = analyses_collection
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
    ) -> InbodyReportDetail:
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

        analysis = await self._run_extraction(
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
    ) -> Optional[InbodyExtraction]:
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
            return None

        final_status = (
            "needs_review"
            if self.extraction_service.needs_review(extraction)
            else "extracted"
        )

        now = datetime.utcnow()
        await self.analyses_collection.update_one(
            {"report_id": str(report_id)},
            {
                "$set": {
                    "report_id": str(report_id),
                    "patient_id": str(patient_id),
                    "analysis": extraction.model_dump(),
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
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
            report_id, final_status, report_date=extracted_date
        )
        logger.info(
            "inbody: report={} status={} confidence={}",
            report_id,
            final_status,
            extraction.extraction_confidence,
        )

        # Contextual insight only on clean extractions — needs_review data
        # could mislead the patient until a human has looked at it.
        if final_status == "extracted":
            try:
                from lib.workers.arq.redis import enqueue_job

                await enqueue_job(
                    "run_inbody_insight",
                    str(report_id),
                    _job_id=f"inbody-insight-{report_id}",
                )
            except Exception as exc:
                logger.error(
                    "inbody: failed to enqueue insight job report={}: {}",
                    report_id,
                    exc,
                )
        return extraction

    async def reextract_report(
        self, patient_id: UUID, report_id: UUID, file_bytes: bytes
    ) -> InbodyReportDetail:
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
    ) -> None:
        async with self.postgres_store.get_session() as session:
            row = await session.get(PatientInbodyReport, report_id)
            if not row:
                return
            row.status = new_status
            row.error = error
            if report_date:
                row.report_date = report_date
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

    async def list_reports(
        self, patient_id: UUID, limit: int = 50
    ) -> List[InbodyReportRecord]:
        async with self.postgres_store.get_session() as session:
            result = await session.execute(
                select(PatientInbodyReport)
                .where(PatientInbodyReport.patient_id == patient_id)
                .order_by(PatientInbodyReport.report_date.desc())
                .limit(limit)
            )
            rows = result.scalars().all()
        return [InbodyReportRecord.model_validate(row) for row in rows]

    async def get_report_detail(
        self, patient_id: UUID, report_id: UUID
    ) -> InbodyReportDetail:
        row = await self._get_row(patient_id, report_id)
        detail = InbodyReportDetail.model_validate(row)
        doc = await self.analyses_collection.find_one(
            {"report_id": str(report_id)}
        )
        if doc and doc.get("analysis"):
            detail.analysis = InbodyExtraction.model_validate(doc["analysis"])
        return detail

    async def get_latest_report(
        self, patient_id: UUID
    ) -> Optional[InbodyReportDetail]:
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
        return await self.get_report_detail(patient_id, row.report_id)

    # ------------------------------------------------------------------
    # Trends
    # ------------------------------------------------------------------

    async def get_trends(
        self,
        patient_id: UUID,
        *,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> InbodyTrendsResponse:
        """Metric time series across all successfully extracted reports."""

        async with self.postgres_store.get_session() as session:
            query = (
                select(PatientInbodyReport)
                .where(
                    PatientInbodyReport.patient_id == patient_id,
                    PatientInbodyReport.status.in_(
                        ["extracted", "needs_review"]
                    ),
                )
                .order_by(PatientInbodyReport.report_date.asc())
            )
            if start_date:
                query = query.where(
                    PatientInbodyReport.report_date >= start_date
                )
            if end_date:
                query = query.where(
                    PatientInbodyReport.report_date <= end_date
                )
            rows = (await session.execute(query)).scalars().all()

        if not rows:
            return InbodyTrendsResponse(
                patient_id=patient_id, reports_count=0, trends=[]
            )

        report_ids = [str(row.report_id) for row in rows]
        date_by_id = {str(row.report_id): row.report_date for row in rows}

        docs: Dict[str, Dict[str, Any]] = {}
        cursor = self.analyses_collection.find(
            {"report_id": {"$in": report_ids}}
        )
        async for doc in cursor:
            docs[doc["report_id"]] = doc.get("analysis") or {}

        trends: List[InbodyTrend] = []
        for metric in TREND_METRICS:
            points: List[TrendPoint] = []
            unit: Optional[str] = None
            for report_id in report_ids:
                analysis = docs.get(report_id)
                if not analysis:
                    continue
                for measurement in analysis.get("measurements", []):
                    if measurement.get("name") == metric and measurement.get(
                        "value"
                    ) is not None:
                        points.append(
                            TrendPoint(
                                report_id=UUID(report_id),
                                report_date=date_by_id[report_id],
                                value=float(measurement["value"]),
                            )
                        )
                        unit = unit or measurement.get("unit")
                        break
            if points:
                trends.append(
                    InbodyTrend(
                        metric=metric,
                        unit=unit,
                        points=points,
                        change=(
                            round(points[-1].value - points[0].value, 2)
                            if len(points) > 1
                            else None
                        ),
                    )
                )

        # InBody score rides alongside measurements in the analysis doc.
        score_points = [
            TrendPoint(
                report_id=UUID(report_id),
                report_date=date_by_id[report_id],
                value=float(docs[report_id]["inbody_score"]),
            )
            for report_id in report_ids
            if docs.get(report_id, {}).get("inbody_score") is not None
        ]
        if score_points:
            trends.append(
                InbodyTrend(
                    metric="inbody_score",
                    unit="points",
                    points=score_points,
                    change=(
                        round(score_points[-1].value - score_points[0].value, 2)
                        if len(score_points) > 1
                        else None
                    ),
                )
            )

        return InbodyTrendsResponse(
            patient_id=patient_id,
            reports_count=len(rows),
            first_report_date=rows[0].report_date,
            last_report_date=rows[-1].report_date,
            trends=trends,
        )
