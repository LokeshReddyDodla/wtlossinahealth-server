from datetime import datetime
import json
from typing import Any, Dict, List, Optional, cast
from uuid import UUID
from fastapi import status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from sqlalchemy import select

from lib.core.mongo_store import MongoStore
from lib.dependencies.database import get_async_postgres_session
from lib.models.patient import Patient
from lib.utils.cgm.processor import CGMReportType
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.patient_mapping import map_patients_to_reports


class CGMMetricsService:
    def __init__(
        self,
        cgm_report_collection,
    ):
        self.cgm_report_collection = cgm_report_collection

    async def find_patients_with_hyper_events(
        self,
        start_date: datetime,
        end_date: datetime,
        health_facility_id: str,
        min_duration_minutes: float = 45,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        try:
            query = {
                "report_type": CGMReportType.DAILY,
                "start_date": {"$gte": start_date},
                "end_date": {"$lte": end_date},
                f"hyper_stats.hyper_events": {
                    "$elemMatch": {"duration": {"$gte": min_duration_minutes}}
                },
            }

            projection = {
                "_id": 1,
                "patient_id": 1,
                "hyper_stats.hyper_events": 1,
            }

            cursor = (
                self.cgm_report_collection.find(query, projection)
                .skip(offset)
                .limit(limit)
            )
            reports = await cursor.to_list(length=limit)
            if not reports:
                return []

            async with get_async_postgres_session() as session:
                return await map_patients_to_reports(
                    reports=reports,
                    health_facility_id=health_facility_id,
                    postgres_session=session,
                    extract_patient_id=lambda r: r["patient_id"],
                    enrich_payload=lambda report, patient: {
                        "_id": str(report["_id"]),
                        "patient_id": report["patient_id"],
                        "hyper_events": [
                            e
                            for e in report["hyper_stats"]["hyper_events"]
                            if e["duration"] >= min_duration_minutes
                        ],
                        "patient": {
                            "name": patient.first_name
                            + " "
                            + patient.last_name,
                            "profile_picture": patient.profile_picture,
                            "gender": patient.gender,
                        },
                    },
                )

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch patients with hyper events",
                detail=str(e),
            )

    async def find_patients_with_hypo_events(
        self,
        start_date: datetime,
        end_date: datetime,
        health_facility_id: str,
        min_duration_minutes: float = 20,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        try:
            query = {
                "report_type": CGMReportType.DAILY,
                "start_date": {"$gte": start_date},
                "end_date": {"$lte": end_date},
                "hypo_stats.hypo_events": {
                    "$elemMatch": {"duration": {"$gte": min_duration_minutes}}
                },
            }

            projection = {
                "_id": 1,
                "patient_id": 1,
                "hypo_stats.hypo_events": 1,
            }

            cursor = (
                self.cgm_report_collection.find(query, projection)
                .skip(offset)
                .limit(limit)
            )
            reports = await cursor.to_list(length=limit)
            if not reports:
                return []

            async with get_async_postgres_session() as session:
                return await map_patients_to_reports(
                    reports=reports,
                    health_facility_id=health_facility_id,
                    postgres_session=session,
                    extract_patient_id=lambda r: r["patient_id"],
                    enrich_payload=lambda report, patient: {
                        "_id": str(report["_id"]),
                        "patient_id": report["patient_id"],
                        "hypo_events": [
                            e
                            for e in report["hypo_stats"]["hypo_events"]
                            if e["duration"] >= min_duration_minutes
                        ],
                        "patient": {
                            "name": patient.first_name
                            + " "
                            + patient.last_name,
                            "profile_picture": patient.profile_picture,
                            "gender": patient.gender,
                        },
                    },
                )

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch patients with hypo events",
                detail=str(e),
            )
