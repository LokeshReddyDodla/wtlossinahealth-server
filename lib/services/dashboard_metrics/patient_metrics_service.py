from typing import List, Optional
from sqlalchemy import Date, cast, func, select
from uuid import UUID
from datetime import datetime
from lib.core.postgres_store import PostgresStore
from lib.dependencies.database import get_async_postgres_session
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session
from lib.models.patient import Patient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from fastapi import status
from lib.models.associations import patient_care_provider_association


class PatientMetricsService:
    async def get_patients(
        self,
        health_facility_id: str,
        care_provider_id: str,
        is_admin: bool,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Patient]:
        try:
            async with get_async_postgres_session() as session:
                if is_admin:
                    stmt = select(Patient).where(
                        Patient.health_facility_id == health_facility_id
                    )
                else:
                    stmt = (
                        select(Patient)
                        .join(patient_care_provider_association)
                        .where(
                            patient_care_provider_association.c.care_provider_id
                            == care_provider_id
                        )
                    )

                if start:
                    stmt = stmt.where(Patient.created_at >= start)
                if end:
                    stmt = stmt.where(Patient.created_at <= end)

                stmt = (
                    stmt.order_by(Patient.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
                result = await session.execute(stmt)
                patients = result.scalars().all()
                return list(patients)

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch total patients enrolled",
                detail=str(e),
            )

    async def get_patient_counts_by_date(
        self,
        health_facility_id: str,
        care_provider_id: str,
        is_admin: bool,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> List[dict]:
        try:
            async with get_async_postgres_session() as session:
                if is_admin:
                    stmt = (
                        select(
                            cast(Patient.created_at, Date).label("date"),
                            func.count().label("count"),
                        )
                        .where(
                            Patient.health_facility_id == health_facility_id
                        )
                        .group_by(cast(Patient.created_at, Date))
                        .order_by("date")
                    )
                else:
                    stmt = (
                        select(
                            cast(Patient.created_at, Date).label("date"),
                            func.count().label("count"),
                        )
                        .select_from(Patient)
                        .join(patient_care_provider_association)
                        .where(
                            patient_care_provider_association.c.care_provider_id
                            == care_provider_id
                        )
                        .group_by(cast(Patient.created_at, Date))
                        .order_by("date")
                    )

                if start:
                    stmt = stmt.where(Patient.created_at >= start)
                if end:
                    stmt = stmt.where(Patient.created_at <= end)

                result = await session.execute(stmt)
                rows = result.all()

                return [
                    {"date": row.date.isoformat(), "count": row.count}
                    for row in rows
                ]
        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to group patients by date",
                detail=str(e),
            )
