from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from sqlalchemy import Date, cast, func, select

from lib.dependencies.database import get_async_postgres_session
from lib.models.patient import Patient
from lib.utils.http_exceptions import raise_http_exception
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from fastapi import status


class FitnessMetricsService:
    async def get_patients_with_low_steps(
        self,
        health_facility_id: str,
        min_steps: int = 1000,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        from lib.dependencies.service_dependencies import (
            get_fitness_report_collection,
        )

        try:

            query = {
                "report_type": "daily",
                "steps": {"$lt": min_steps},
            }

            if start_date and end_date:
                query["start_date"] = {"$gte": start_date}
                query["end_date"] = {"$lte": end_date}

            # Get reports
            mongo_db = get_fitness_report_collection()
            cursor = mongo_db.find(query).skip(offset).limit(limit)  # type: ignore
            reports = await cursor.to_list(length=limit)

            if not reports:
                return []

            # Unique patient IDs
            patient_ids = list({r["patient_id"] for r in reports})

            async with get_async_postgres_session() as session:
                stmt = select(Patient).where(
                    Patient.patient_id.in_(patient_ids),
                    Patient.health_facility_id == health_facility_id,
                )
                result = await session.execute(stmt)
                patients = {p.patient_id: p for p in result.scalars().all()}

                return [
                    {
                        "_id": str(report["_id"]),
                        "patient_id": report["patient_id"],
                        "steps": report.get("steps"),
                        "active_duration": report.get("active_duration"),
                        "start_date": report.get("start_date"),
                        "patient": {
                            "name": patient.first_name
                            + " "
                            + patient.last_name,
                            "profile_picture": patient.profile_picture,
                            "gender": patient.gender,
                        },
                    }
                    for report in reports
                    if (patient := patients.get(UUID(report["patient_id"])))
                ]

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch total patients enrolled",
                detail=str(e),
            )
