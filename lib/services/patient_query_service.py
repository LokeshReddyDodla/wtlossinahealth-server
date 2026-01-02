from datetime import datetime
from typing import Dict, Optional

from dateutil.relativedelta import relativedelta
from lib.core.postgres_store import PostgresStore
from lib.utils.postgres_session_decorator import with_postgres_session
from sqlalchemy import asc, desc, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import Select

from lib.core.constants import ProfileTypeEnum
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.models.patient import Patient as PatientModel
from lib.models.patient_connected_app import PatientConnectedApp
from lib.models.patient_package_assignment import (
    PatientPackageAssignment as PatientPackageAssignmentModel,
)
from lib.models.patient_smbg import PatientSMBG
from lib.models.user_device import UserDevice as UserDeviceModel
from lib.queries.patient_query import PatientQuery


class PatientQueryService:
    AGE_RANGES: Dict[str, Optional[tuple[int, Optional[int]]]] = {
        "under18": (None, 18),
        "18-25": (18, 25),
        "26-35": (26, 35),
        "36-45": (36, 45),
        "46-60": (46, 60),
        "60+": (60, None),
    }

    ORDER_FIELDS: Dict[str, any] = {
        "first_name": PatientModel.first_name,
        "last_name": PatientModel.last_name,
        "email": PatientModel.email,
        "created_at": PatientModel.created_at,
        "dob": PatientModel.dob,
        "age": PatientModel.age,
    }

    CONNECTED_APP_FIELDS: Dict[str, any] = {
        "libreview": PatientConnectedApp.libreview,
        "sinocare": PatientConnectedApp.sinocare,
    }

    def __init__(self, postgres_store: PostgresStore):
        self.postgres_store = postgres_store

    @with_postgres_session
    async def fetch(
        self,
        query: PatientQuery,
        *,
        postgres_session: AsyncSession,
    ) -> list[PatientModel]:
        """Fetch patients based on query parameters."""
        stmt = self._build_base_query()
        stmt = self._apply_all_filters(stmt, query)
        stmt = self._apply_ordering(stmt, query)
        stmt = self._apply_pagination(stmt, query)

        result = await postgres_session.execute(stmt)
        return list(result.scalars().all())

    @with_postgres_session
    async def count(
        self,
        query: PatientQuery,
        *,
        postgres_session: AsyncSession,
    ) -> int:
        """Count patients matching query filters (without pagination)."""
        stmt = select(func.count(func.distinct(PatientModel.patient_id)))
        stmt = self._apply_all_filters(stmt, query)

        result = await postgres_session.execute(stmt)
        return result.scalar() or 0

    def _apply_all_filters(self, stmt: Select, query: PatientQuery) -> Select:
        """Apply all filters to the query statement."""
        stmt = self._apply_scope_filters(stmt, query)
        stmt = self._apply_search_filter(stmt, query)
        stmt = self._apply_gender_filter(stmt, query)
        stmt = self._apply_age_filter(stmt, query)
        stmt = self._apply_monitoring_method_filter(stmt, query)
        stmt = self._apply_package_filter(stmt, query)
        stmt = self._apply_connected_apps_filter(stmt, query)
        return stmt

    def _build_base_query(self) -> Select:
        """Build base query with eager loading."""
        self._last_active_sq = self._build_last_active_subquery()

        return (
            select(PatientModel)
            .outerjoin(
                self._last_active_sq,
                PatientModel.patient_id == self._last_active_sq.c.user_id,
            )
            .options(
                selectinload(PatientModel.health_facility),
                selectinload(PatientModel.care_providers),
                selectinload(PatientModel.package_assignments).selectinload(
                    PatientPackageAssignmentModel.package
                ),
            )
        )

    def _apply_scope_filters(self, stmt: Select, query: PatientQuery) -> Select:
        """Apply scope filters (health_facility vs care_provider)."""
        if query.health_facility_id:
            stmt = stmt.where(
                PatientModel.health_facility_id == query.health_facility_id
            )
        elif query.care_provider_id:
            stmt = stmt.join(PatientModel.care_providers).where(
                CareProviderModel.care_provider_id == query.care_provider_id
            )
        return stmt

    def _apply_search_filter(self, stmt: Select, query: PatientQuery) -> Select:
        """Apply search filter across name, email, and phone."""
        if not query.search:
            return stmt

        search_pattern = f"%{query.search}%"
        return stmt.where(
            or_(
                PatientModel.first_name.ilike(search_pattern),
                PatientModel.last_name.ilike(search_pattern),
                PatientModel.email.ilike(search_pattern),
                PatientModel.phone_number.ilike(search_pattern),
            )
        )

    def _apply_gender_filter(self, stmt: Select, query: PatientQuery) -> Select:
        """Apply gender filter."""
        if query.gender:
            stmt = stmt.where(PatientModel.gender.in_(query.gender))
        return stmt

    def _apply_age_filter(self, stmt: Select, query: PatientQuery) -> Select:
        """Apply age range filters (converts age ranges to DOB ranges)."""
        if not query.age:
            return stmt

        age_conditions = []
        today = datetime.today().date()

        for age_group in query.age:
            if age_group not in self.AGE_RANGES:
                continue

            min_years, max_years = self.AGE_RANGES[age_group]

            if max_years is None:
                # "60+" case
                cutoff = today - relativedelta(years=min_years)
                age_conditions.append(PatientModel.dob <= cutoff)
            elif min_years is None:
                # "under18" case
                cutoff = today - relativedelta(years=max_years)
                age_conditions.append(PatientModel.dob > cutoff)
            else:
                # Range case (e.g., "18-25")
                cutoff_max = today - relativedelta(years=min_years)
                cutoff_min = today - relativedelta(years=max_years)
                age_conditions.append(PatientModel.dob.between(cutoff_min, cutoff_max))

        if age_conditions:
            stmt = stmt.where(or_(*age_conditions))
        return stmt

    def _apply_monitoring_method_filter(
        self, stmt: Select, query: PatientQuery
    ) -> Select:
        """Apply monitoring method filter (SMBG/CGM)."""
        if not query.monitoring_method:
            return stmt

        conditions = []
        for method in query.monitoring_method:
            if method == "smbg":
                conditions.append(
                    exists().where(PatientSMBG.patient_id == PatientModel.patient_id)
                )
            # CGM filtering typically done post-query via MongoDB reports

        if conditions:
            stmt = stmt.where(or_(*conditions))
        return stmt

    def _apply_package_filter(self, stmt: Select, query: PatientQuery) -> Select:
        """Apply package assignment filters."""
        if not query.package:
            return stmt

        package_exists = exists().where(
            PatientPackageAssignmentModel.patient_id == PatientModel.patient_id
        )

        conditions = []
        if "on-package" in query.package:
            conditions.append(package_exists)
        if "no-package" in query.package:
            conditions.append(~package_exists)

        if conditions:
            stmt = stmt.where(or_(*conditions))
        return stmt

    def _apply_connected_apps_filter(self, stmt: Select, query: PatientQuery) -> Select:
        """Apply connected apps filter (libreview, sinocare)."""
        if not query.connected_apps:
            return stmt

        stmt = stmt.outerjoin(PatientModel.connected_apps)
        conditions = []

        for app in query.connected_apps:
            field = self.CONNECTED_APP_FIELDS.get(app)
            if field is not None:
                conditions.append(field != None)  # noqa: E711

        if conditions:
            stmt = stmt.where(or_(*conditions))
        return stmt

    def _build_last_active_subquery(self):
        """Build subquery for last_active_at aggregation."""
        return (
            select(
                UserDeviceModel.user_id.label("user_id"),
                func.max(UserDeviceModel.last_active_at).label("last_active_at"),
            )
            .where(UserDeviceModel.profile_type == ProfileTypeEnum.PATIENT.value)
            .group_by(UserDeviceModel.user_id)
            .subquery(name="last_active")
        )

    def _apply_ordering(self, stmt: Select, query: PatientQuery) -> Select:
        """Apply ordering to the query."""
        order_by = query.order_by or "last_active_at"
        is_desc = query.order and query.order.lower() == "desc"

        if order_by == "last_active_at":
            col = self._last_active_sq.c.last_active_at

            return stmt.order_by(
                desc(col).nulls_last() if is_desc else asc(col).nulls_first(),
                desc(PatientModel.created_at),
            )

        # For other fields, use direct column ordering
        if order_by in self.ORDER_FIELDS:
            order_func = desc if is_desc else asc
            stmt = stmt.order_by(order_func(self.ORDER_FIELDS[order_by]))
        

        return stmt.order_by(desc(PatientModel.created_at))

    def _apply_pagination(self, stmt: Select, query: PatientQuery) -> Select:
        """Apply pagination (offset and limit)."""
        if query.offset:
            stmt = stmt.offset(query.offset)
        if query.limit:
            stmt = stmt.limit(query.limit)
        return stmt
