from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import status
from sqlalchemy.exc import SQLAlchemyError

from lib.dependencies.database import get_async_postgres_session
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

    def _build_report_type_query(self, report_type: str) -> Dict[str, Any]:
        return {
            "$or": [
                {"metadata.report_type": report_type},
                {"report_type": report_type},
            ]
        }

    def _build_date_range_query(
        self, start: datetime, end: datetime
    ) -> Dict[str, Any]:
        start_iso = start.isoformat()
        end_iso = end.isoformat()
        return {
            "$or": [
                {
                    "metadata.date_range.start": {"$gte": start_iso},
                    "metadata.date_range.end": {"$lte": end_iso},
                },
                {"start_date": {"$gte": start}, "end_date": {"$lte": end}},
                {"start_date": {"$gte": start_iso}, "end_date": {"$lte": end_iso}},
            ]
        }

    def _extract_report_start(self, report: Dict[str, Any]) -> Optional[str]:
        metadata_start = (
            report.get("metadata", {})
            .get("date_range", {})
            .get("start")
        )
        if metadata_start:
            return metadata_start
        start_date = report.get("start_date")
        if isinstance(start_date, datetime):
            return start_date.isoformat()
        if isinstance(start_date, str):
            return start_date
        return None

    def _build_patient_payload(self, patient) -> Dict[str, Any]:
        return {
            "name": patient.first_name + " " + patient.last_name,
            "profile_picture": patient.profile_picture,
            "gender": patient.gender,
            "age": calculate_age(patient.dob),
            "diabetic_history": (
                PatientDiabeticHistory.from_orm(patient.diabetic_history)
                if patient.diabetic_history
                else None
            ),
        }

    def _extract_events(
        self, report: Dict[str, Any], stats_key: str, events_key: str
    ) -> List[Dict[str, Any]]:
        stats = report.get(stats_key) or {}
        events = stats.get(events_key) or []
        return [event for event in events if isinstance(event, dict)]

    async def _find_patients_with_events(
        self,
        *,
        start: datetime,
        end: datetime,
        stats_key: str,
        events_key: str,
        min_duration_minutes: float,
        health_facility_id: Optional[str],
        care_provider_id: Optional[str],
        is_facility_admin: bool,
        limit: int,
        offset: int,
    ) -> List[Dict[str, Any]]:
        try:
            query = {
                "$and": [
                    self._build_report_type_query(CGMReportType.DAILY),
                    self._build_date_range_query(start, end),
                    {
                        f"{stats_key}.{events_key}": {
                            "$elemMatch": {
                                "duration_minutes": {
                                    "$gte": min_duration_minutes
                                }
                            }
                        }
                    },
                ]
            }

            projection = {
                "_id": 1,
                "patient_id": 1,
                f"{stats_key}.{events_key}": 1,
                "metadata.date_range.start": 1,
                "start_date": 1,
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
                        events_key: [
                            event
                            for event in self._extract_events(
                                report,
                                stats_key=stats_key,
                                events_key=events_key,
                            )
                            if event.get("duration_minutes", 0)
                            >= min_duration_minutes
                        ],
                        "date": self._extract_report_start(report),
                        "patient": self._build_patient_payload(patient),
                    },
                )
        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch patients with CGM events",
                detail=str(e),
            )

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
        return await self._find_patients_with_events(
            start=start,
            end=end,
            stats_key="hyper_stats",
            events_key="hyper_events",
            min_duration_minutes=min_duration_minutes,
            health_facility_id=health_facility_id,
            care_provider_id=care_provider_id,
            is_facility_admin=is_facility_admin,
            limit=limit,
            offset=offset,
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
        return await self._find_patients_with_events(
            start=start,
            end=end,
            stats_key="hypo_stats",
            events_key="hypo_events",
            min_duration_minutes=min_duration_minutes,
            health_facility_id=health_facility_id,
            care_provider_id=care_provider_id,
            is_facility_admin=is_facility_admin,
            limit=limit,
            offset=offset,
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
            query = {
                "$and": [
                    self._build_report_type_query(CGMReportType.DAILY),
                    self._build_date_range_query(start, end),
                    {
                        "cgm_summary_stats.glucose_variability_percent": {
                            "$gt": gv_threshold
                        }
                    },
                ]
            }

            projection = {
                "_id": 1,
                "patient_id": 1,
                "metadata.date_range.start": 1,
                "start_date": 1,
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
                        "date": self._extract_report_start(report),
                        "patient": self._build_patient_payload(patient),
                    },
                )

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch patients with high glucose variability",
                detail=str(e),
            )
