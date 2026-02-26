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
from lib.schemas.patient_diabetic_history import PatientDiabeticHistory
from lib.services.reports import CGMReportType
from lib.utils.date.age_utils import calculate_age
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
        start: datetime,
        end: datetime,
        health_facility_id: Optional[str] = None,
        care_provider_id: Optional[str] = None,
        is_facility_admin: bool = False,
        min_duration_minutes: float = 45,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        try:
            start_iso = start.isoformat()
            end_iso = end.isoformat()

            query = {
                "metadata.report_type": CGMReportType.DAILY,
                "metadata.date_range.start": {"$gte": start_iso},
                "metadata.date_range.end": {"$lte": end_iso},
                f"hyper_stats.hyper_events": {
                    "$elemMatch": {"duration_minutes": {"$gte": min_duration_minutes}}
                },
            }

            projection = {
                "_id": 1,
                "patient_id": 1,
                "hyper_stats.hyper_events": 1,
            }

            cursor = (
                self.cgm_report_collection.find(query, projection)
                .sort("metadata.date_range.start", -1)
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
                    care_provider_id=care_provider_id,
                    is_facility_admin=is_facility_admin,
                    postgres_session=session,
                    extract_patient_id=lambda r: r["patient_id"],
                    enrich_payload=lambda report, patient: {
                        "_id": str(report["_id"]),
                        "patient_id": report["patient_id"],
                        "hyper_events": [
                            e
                            for e in report["hyper_stats"]["hyper_events"]
                            if e.get("duration_minutes", 0) >= min_duration_minutes
                        ],
                        "patient": {
                            "name": patient.first_name
                            + " "
                            + patient.last_name,
                            "profile_picture": patient.profile_picture,
                            "gender": patient.gender,
                            "age": calculate_age(patient.dob),
                            "diabetic_history": (
                                PatientDiabeticHistory.from_orm(
                                    patient.diabetic_history
                                )
                                if patient.diabetic_history
                                else None
                            ),
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
        start: datetime,
        end: datetime,
        health_facility_id: Optional[str] = None,
        care_provider_id: Optional[str] = None,
        is_facility_admin: bool = False,
        min_duration_minutes: float = 20,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        try:
            start_iso = start.isoformat()
            end_iso = end.isoformat()

            query = {
                "metadata.report_type": CGMReportType.DAILY,
                "metadata.date_range.start": {"$gte": start_iso},
                "metadata.date_range.end": {"$lte": end_iso},
                "hypo_stats.hypo_events": {
                    "$elemMatch": {"duration_minutes": {"$gte": min_duration_minutes}}
                },
            }

            projection = {
                "_id": 1,
                "patient_id": 1,
                "hypo_stats.hypo_events": 1,
            }

            cursor = (
                self.cgm_report_collection.find(query, projection)
                .sort("metadata.date_range.start", -1)
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
                    care_provider_id=care_provider_id,
                    is_facility_admin=is_facility_admin,
                    postgres_session=session,
                    extract_patient_id=lambda r: r["patient_id"],
                    enrich_payload=lambda report, patient: {
                        "_id": str(report["_id"]),
                        "patient_id": report["patient_id"],
                        "hypo_events": [
                            e
                            for e in report["hypo_stats"]["hypo_events"]
                            if e.get("duration_minutes", 0) >= min_duration_minutes
                        ],
                        "patient": {
                            "name": patient.first_name
                            + " "
                            + patient.last_name,
                            "profile_picture": patient.profile_picture,
                            "gender": patient.gender,
                            "age": calculate_age(patient.dob),
                            "diabetic_history": (
                                PatientDiabeticHistory.from_orm(
                                    patient.diabetic_history
                                )
                                if patient.diabetic_history
                                else None
                            ),
                        },
                    },
                )

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch patients with hypo events",
                detail=str(e),
            )

    async def find_patients_with_high_glucose_variability(
        self,
        start: datetime,
        end: datetime,
        health_facility_id: Optional[str] = None,
        care_provider_id: Optional[str] = None,
        is_facility_admin: bool = False,
        gv_threshold: float = 20.0,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        try:
            start_iso = start.isoformat()
            end_iso = end.isoformat()

            query = {
                "metadata.report_type": CGMReportType.DAILY,
                "metadata.date_range.start": {"$gte": start_iso},
                "metadata.date_range.end": {"$lte": end_iso},
                "cgm_summary_stats.glucose_variability_percent": {"$gt": gv_threshold},
            }

            projection = {
                "_id": 1,
                "patient_id": 1,
                "metadata.date_range.start": 1,
                "cgm_summary_stats.glucose_variability_percent": 1,
            }

            cursor = (
                self.cgm_report_collection.find(query, projection)
                .sort("metadata.date_range.start", -1)
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
                    care_provider_id=care_provider_id,
                    is_facility_admin=is_facility_admin,
                    postgres_session=session,
                    extract_patient_id=lambda r: r["patient_id"],
                    enrich_payload=lambda report, patient: {
                        "_id": str(report["_id"]),
                        "patient_id": report["patient_id"],
                        "glucose_variability": report.get("cgm_summary_stats", {}).get(
                            "glucose_variability_percent"
                        ),
                        "date": report.get("metadata", {}).get("date_range", {}).get("start"),
                        "patient": {
                            "name": patient.first_name
                            + " "
                            + patient.last_name,
                            "profile_picture": patient.profile_picture,
                            "gender": patient.gender,
                            "age": calculate_age(patient.dob),
                            "diabetic_history": (
                                PatientDiabeticHistory.from_orm(
                                    patient.diabetic_history
                                )
                                if patient.diabetic_history
                                else None
                            ),
                        },
                    },
                )

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch patients with high glucose variability",
                detail=str(e),
            )
