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
        health_facility_id: Optional[str] = None,
        care_provider_id: Optional[str] = None,
        is_facility_admin: bool = False,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Patient]:
        try:
            async with get_async_postgres_session() as session:
                stmt = select(Patient)

                stmt = self._apply_patient_scope_filters(
                    stmt,
                    health_facility_id=health_facility_id,
                    care_provider_id=care_provider_id,
                    is_facility_admin=is_facility_admin,
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
                return result.scalars().all()

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch patients",
                detail=str(e),
            )

    async def get_enrolled_patient_counts_by_date(
        self,
        health_facility_id: Optional[str] = None,
        care_provider_id: Optional[str] = None,
        is_facility_admin: bool = False,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> List[dict]:
        try:
            async with get_async_postgres_session() as session:
                stmt = select(
                    cast(Patient.created_at, Date).label("date"),
                    func.count().label("count"),
                ).select_from(Patient)

                stmt = self._apply_patient_scope_filters(
                    stmt,
                    health_facility_id=health_facility_id,
                    care_provider_id=care_provider_id,
                    is_facility_admin=is_facility_admin,
                )

                if start:
                    stmt = stmt.where(Patient.created_at >= start)
                if end:
                    stmt = stmt.where(Patient.created_at <= end)

                stmt = stmt.group_by(cast(Patient.created_at, Date)).order_by(
                    "date"
                )

                result = await session.execute(stmt)

                return [
                    {"date": row.date.isoformat(), "count": row.count}
                    for row in result.all()
                ]

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to group patients by date",
                detail=str(e),
            )

    async def get_active_patient_count(
        self,
        health_facility_id: Optional[str] = None,
        care_provider_id: Optional[str] = None,
        is_facility_admin: bool = False,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> int:
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

                stmt = self._apply_patient_scope_filters(
                    stmt,
                    health_facility_id=health_facility_id,
                    care_provider_id=care_provider_id,
                    is_facility_admin=is_facility_admin,
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
        health_facility_id: Optional[str] = None,
        care_provider_id: Optional[str] = None,
        is_facility_admin: bool = False,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> List[dict]:
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
                    .where(
                        UserActivityLog.profile_type
                        == ProfileTypeEnum.PATIENT.value
                    )
                )

                stmt = self._apply_patient_scope_filters(
                    stmt,
                    health_facility_id=health_facility_id,
                    care_provider_id=care_provider_id,
                    is_facility_admin=is_facility_admin,
                )

                if start:
                    stmt = stmt.where(UserActivityLog.active_at >= start)
                if end:
                    stmt = stmt.where(UserActivityLog.active_at <= end)

                stmt = stmt.group_by(
                    cast(UserActivityLog.active_at, Date)
                ).order_by("date")

                result = await session.execute(stmt)

                return [
                    {"date": row.date.isoformat(), "count": row.count}
                    for row in result.all()
                ]

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to group active patients by date",
                detail=str(e),
            )

    def _apply_patient_scope_filters(
        stmt,
        *,
        health_facility_id: Optional[str] = None,
        care_provider_id: Optional[str] = None,
        is_facility_admin: bool = False,
    ):
        if health_facility_id and is_facility_admin:
            return stmt.where(Patient.health_facility_id == health_facility_id)

        if care_provider_id:
            stmt = stmt.join(patient_care_provider_association).where(
                patient_care_provider_association.c.care_provider_id
                == care_provider_id
            )

        return stmt
