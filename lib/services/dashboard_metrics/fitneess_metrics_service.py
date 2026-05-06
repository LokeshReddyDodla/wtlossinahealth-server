from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from sqlalchemy import select

from lib.dependencies.database import get_async_postgres_session
from lib.models.patient import Patient
from lib.schemas.patient_diabetic_history import PatientDiabeticHistory
from lib.utils.date.age_utils import calculate_age
from lib.services.reports import FitnessReportType
from lib.utils.http_exceptions import raise_http_exception
from sqlalchemy.exc import SQLAlchemyError
from fastapi import status

from lib.utils.patient_mapping import map_patients_to_reports


class FitnessMetricsService:
    def __init__(
        self,
        fitness_report_collection,
    ):
        self.fitness_report_collection = fitness_report_collection

    async def get_patients_by_step_threshold(
        self,
        health_facility_id: Optional[str] = None,
        care_provider_id: Optional[str] = None,
        is_facility_admin: bool = False,
        steps_op: str = "lt",
        steps_value: int = 1000,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        try:
            op_map = {
                "lt": "$lt",
                "lte": "$lte",
                "gt": "$gt",
                "gte": "$gte",
                "eq": "$eq",
            }

            mongo_op = op_map.get(steps_op)
            if not mongo_op:
                raise ValueError(f"Invalid operator: {steps_op}")

            query = {
                "metadata.report_type": FitnessReportType.DAILY,
                "steps": {mongo_op: steps_value},
            }

            if start and end:
                query["metadata.date_range.start"] = {"$gte": start.isoformat()}
                query["metadata.date_range.end"] = {"$lte": end.isoformat()}

            # Get reports
            cursor = (
                self.fitness_report_collection.find(query)
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
                        "steps": report.get("steps"),
                        "active_duration": report.get("active_duration"),
                        "start_date": report.get("metadata", {})
                        .get("date_range", {})
                        .get("start"),
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
                message="Failed to fetch total patients enrolled",
                detail=str(e),
            )
