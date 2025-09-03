from typing import List, Optional
from sqlalchemy import Date, cast, distinct, func, select
from uuid import UUID
from datetime import datetime
from lib.core.constants import ProfileTypeEnum
from lib.dependencies.database import get_async_postgres_session
from lib.models.user_activity_log import UserActivityLog
from lib.models.user_device import UserDevice
from lib.utils.http_exceptions import raise_http_exception
from lib.models.patient import Patient
from sqlalchemy.exc import SQLAlchemyError
from fastapi import status
from lib.models.associations import patient_care_provider_association


class PatientMetricsService:
    async def get_enrolled_patients(
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

    async def get_enrolled_patient_counts_by_date(
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

    async def get_active_patient_count(
        self,
        health_facility_id: str,
        care_provider_id: str,
        is_admin: bool,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> int:
        """
        Returns count of unique patients whose most recent device activity is between start and end.
        """
        try:
            async with get_async_postgres_session() as session:
                stmt = (
                    select(func.count(distinct(UserActivityLog.user_id)))
                    .select_from(UserActivityLog)
                    .join(
                        Patient, Patient.patient_id == UserActivityLog.user_id
                    )
                    .where(
                        UserActivityLog.profile_type
                        == ProfileTypeEnum.PATIENT.value
                    )
                )

                if is_admin:
                    stmt = stmt.where(
                        Patient.health_facility_id == health_facility_id
                    )
                else:
                    stmt = stmt.join(patient_care_provider_association).where(
                        patient_care_provider_association.c.care_provider_id
                        == care_provider_id
                    )

                if start:
                    stmt = stmt.where(UserActivityLog.active_at >= start)
                if end:
                    stmt = stmt.where(UserActivityLog.active_at <= end)

                result = await session.execute(stmt)
                return result.scalar() or 0

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch active patient count",
                detail=str(e),
            )

    async def get_active_patients_by_date(
        self,
        health_facility_id: str,
        care_provider_id: str,
        is_admin: bool,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> List[dict]:
        """
        Returns daily counts of unique active patients based on activity logs.
        """
        try:
            async with get_async_postgres_session() as session:
                stmt = (
                    select(
                        cast(UserActivityLog.active_at, Date).label("date"),
                        func.count(distinct(UserActivityLog.user_id)).label(
                            "count"
                        ),
                    )
                    .select_from(UserActivityLog)
                    .join(
                        Patient, Patient.patient_id == UserActivityLog.user_id
                    )
                    .where(UserActivityLog.profile_type == "patient")
                )

                if is_admin:
                    stmt = stmt.where(
                        Patient.health_facility_id == health_facility_id
                    )
                else:
                    stmt = stmt.join(patient_care_provider_association).where(
                        patient_care_provider_association.c.care_provider_id
                        == care_provider_id
                    )

                if start:
                    stmt = stmt.where(UserActivityLog.active_at >= start)
                if end:
                    stmt = stmt.where(UserActivityLog.active_at <= end)

                stmt = stmt.group_by(
                    cast(UserActivityLog.active_at, Date)
                ).order_by("date")

                result = await session.execute(stmt)
                rows = result.all()

                return [
                    {"date": row.date.isoformat(), "count": row.count}
                    for row in rows
                ]

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to group active patients by date",
                detail=str(e),
            )
