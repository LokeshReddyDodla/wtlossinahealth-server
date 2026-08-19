from typing import Dict

from lib.core.postgres_store import PostgresStore
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.models.package import Package as PackageModel, PackageStatus
from lib.queries.package_query import PackageQuery
from lib.utils.postgres_session_decorator import with_postgres_session
from sqlalchemy import asc, cast, desc, func, or_, select, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import Select

from lib.models.patient_package_assignment import (
    PatientPackageAssignment as PatientPackageAssignmentModel,
)


class PackageQueryService:
    ORDER_FIELDS: Dict[str, any] = {
        "name": PackageModel.name,
        "duration_days": PackageModel.duration_days,
        "price": PackageModel.price,
        "created_at": PackageModel.created_at,
    }

    def __init__(self, postgres_store: PostgresStore):
        self.postgres_store = postgres_store

    @with_postgres_session
    async def fetch(
        self,
        query: PackageQuery,
        *,
        postgres_session: AsyncSession,
    ) -> list[PackageModel]:
        """Fetch packages based on query parameters."""
        stmt = self._build_base_query()
        stmt = self._apply_all_filters(stmt, query)
        stmt = self._apply_ordering(stmt, query)
        stmt = self._apply_pagination(stmt, query)

        result = await postgres_session.execute(stmt)
        return list(result.scalars().all())

    @with_postgres_session
    async def count(
        self,
        query: PackageQuery,
        *,
        postgres_session: AsyncSession,
    ) -> int:
        """Count packages matching query filters (without pagination)."""
        stmt = select(func.count(func.distinct(PackageModel.package_id)))
        stmt = self._apply_all_filters(stmt, query)

        result = await postgres_session.execute(stmt)
        return result.scalar() or 0

    def _build_base_query(self) -> Select:
        """Build base query with eager loading."""
        return select(PackageModel).options(
            selectinload(PackageModel.health_facility),
            selectinload(PackageModel.care_providers),
            selectinload(PackageModel.patient_assignments).selectinload(
                PatientPackageAssignmentModel.patient
            ),
        )

    def _apply_all_filters(self, stmt: Select, query: PackageQuery) -> Select:
        """Apply all filters to the query statement."""
        stmt = self._apply_scope_filters(stmt, query)
        stmt = self._apply_search_filter(stmt, query)
        stmt = self._apply_status_filter(stmt, query)
        stmt = self._apply_type_filter(stmt, query)
        return stmt

    def _apply_scope_filters(self, stmt: Select, query: PackageQuery) -> Select:
        """Apply scope filters (health_facility vs care_provider)."""
        if query.health_facility_id:
            stmt = stmt.where(
                PackageModel.health_facility_id == query.health_facility_id
            )
        if query.care_provider_id:
            stmt = stmt.join(PackageModel.care_providers).where(
                CareProviderModel.care_provider_id == query.care_provider_id
            )
        return stmt

    def _apply_search_filter(self, stmt: Select, query: PackageQuery) -> Select:
        """Search across name, code, package_id; numeric terms also match an
        exact duration_days or price."""
        if not query.search:
            return stmt

        for term in query.search.split():
            pattern = f"%{term}%"
            conditions = [
                PackageModel.name.ilike(pattern),
                PackageModel.code.ilike(pattern),
                cast(PackageModel.package_id, String).ilike(pattern),
            ]
            try:
                n = int(float(term))
                conditions += [
                    PackageModel.duration_days == n,
                    PackageModel.price == n,
                ]
            except (ValueError, TypeError):
                pass
            stmt = stmt.where(or_(*conditions))
        return stmt

    def _apply_status_filter(self, stmt: Select, query: PackageQuery) -> Select:
        """Apply status filter."""
        if query.status:
            # Convert string status to PackageStatus enum
            status_enum_values = []
            for s in query.status:
                try:
                    status_enum_values.append(PackageStatus(s.lower()))
                except ValueError:
                    # Skip invalid status values
                    continue
            
            if status_enum_values:
                stmt = stmt.where(PackageModel.status.in_(status_enum_values))
        return stmt

    def _apply_type_filter(self, stmt: Select, query: PackageQuery) -> Select:
        """Apply package_type filter."""
        if query.type:
            stmt = stmt.where(PackageModel.package_type.in_(query.type))
        return stmt

    def _apply_ordering(self, stmt: Select, query: PackageQuery) -> Select:
        """Apply ordering to the query."""
        order_by = query.order_by or "created_at"
        is_desc = query.order and query.order.lower() == "desc"

        if order_by in self.ORDER_FIELDS:
            order_func = desc if is_desc else asc
            field = self.ORDER_FIELDS[order_by]
            stmt = stmt.order_by(order_func(field))
        else:
            # Fallback to default
            stmt = stmt.order_by(desc(PackageModel.created_at))

        return stmt

    def _apply_pagination(self, stmt: Select, query: PackageQuery) -> Select:
        """Apply pagination (offset and limit)."""
        if query.offset:
            stmt = stmt.offset(query.offset)
        if query.limit:
            stmt = stmt.limit(query.limit)
        return stmt

