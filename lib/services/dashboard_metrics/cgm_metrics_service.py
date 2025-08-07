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
from lib.utils.cgm.processor import CGMReportType
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
        health_facility_id: str,
        care_provider_id: str,
        is_admin: bool,
        min_duration_minutes: float = 45,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        try:
            query = {
                "report_type": CGMReportType.DAILY,
                "start_date": {"$gte": start},
                "end_date": {"$lte": end},
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
                .sort("start_date", -1)
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
                    is_admin=is_admin,
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
        health_facility_id: str,
        care_provider_id: str,
        is_admin: bool,
        min_duration_minutes: float = 20,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        try:
            query = {
                "report_type": CGMReportType.DAILY,
                "start_date": {"$gte": start},
                "end_date": {"$lte": end},
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
                .sort("start_date", -1)
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
                    is_admin=is_admin,
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
        health_facility_id: str,
        care_provider_id: str,
        is_admin: bool,
        gv_threshold: float = 20.0,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        try:
            query = {
                "report_type": CGMReportType.DAILY,
                "start_date": {"$gte": start},
                "end_date": {"$lte": end},
                "cgm_summary_stats.glucose_variability": {"$gt": gv_threshold},
            }

            projection = {
                "_id": 1,
                "patient_id": 1,
                "start_date": 1,
                "cgm_summary_stats.glucose_variability": 1,
            }

            cursor = (
                self.cgm_report_collection.find(query, projection)
                .sort("start_date", -1)
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
                    is_admin=is_admin,
                    postgres_session=session,
                    extract_patient_id=lambda r: r["patient_id"],
                    enrich_payload=lambda report, patient: {
                        "_id": str(report["_id"]),
                        "patient_id": report["patient_id"],
                        "glucose_variability": report["cgm_summary_stats"][
                            "glucose_variability"
                        ],
                        "date": report["start_date"],
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
