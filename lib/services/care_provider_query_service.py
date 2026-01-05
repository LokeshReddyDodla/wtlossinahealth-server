from typing import Dict, Optional

from lib.core.postgres_store import PostgresStore
from lib.utils.postgres_session_decorator import with_postgres_session
from sqlalchemy import asc, desc, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import Select

from lib.models.care_provider import CareProvider as CareProviderModel
from lib.queries.care_provider_query import CareProviderQuery


class CareProviderQueryService:
    ORDER_FIELDS: Dict[str, any] = {
        "name": CareProviderModel.full_name,
        "role": CareProviderModel.role,
        "created_at": CareProviderModel.created_at,
        "is_verified": CareProviderModel.is_verified,
    }

    def __init__(self, postgres_store: PostgresStore):
        self.postgres_store = postgres_store

    @with_postgres_session
    async def fetch(
        self,
        query: CareProviderQuery,
        *,
        postgres_session: AsyncSession,
    ) -> list[CareProviderModel]:
        """Fetch care providers based on query parameters."""
        stmt = self._build_base_query()
        stmt = self._apply_all_filters(stmt, query)
        stmt = self._apply_ordering(stmt, query)
        stmt = self._apply_pagination(stmt, query)

        result = await postgres_session.execute(stmt)
        return list(result.scalars().all())

    @with_postgres_session
    async def count(
        self,
        query: CareProviderQuery,
        *,
        postgres_session: AsyncSession,
    ) -> int:
        """Count care providers matching query filters (without pagination)."""
        stmt = select(func.count(func.distinct(CareProviderModel.care_provider_id)))
        stmt = self._apply_all_filters(stmt, query)

        result = await postgres_session.execute(stmt)
        return result.scalar() or 0

    def _build_base_query(self) -> Select:
        """Build base query with eager loading."""
        return select(CareProviderModel).options(
            selectinload(CareProviderModel.health_facility),
            selectinload(CareProviderModel.patients),
            selectinload(CareProviderModel.packages),
        )

    def _apply_all_filters(self, stmt: Select, query: CareProviderQuery) -> Select:
        """Apply all filters to the query statement."""
        stmt = self._apply_scope_filters(stmt, query)
        stmt = self._apply_search_filter(stmt, query)
        stmt = self._apply_role_filter(stmt, query)
        return stmt

    def _apply_scope_filters(
        self, stmt: Select, query: CareProviderQuery
    ) -> Select:
        """Apply scope filters (health_facility)."""
        if query.health_facility_id:
            stmt = stmt.where(
                CareProviderModel.health_facility_id == query.health_facility_id
            )
        return stmt

    def _apply_search_filter(self, stmt: Select, query: CareProviderQuery) -> Select:
        """Apply search filter across name, email, phone, and identifiers."""
        if not query.search:
            return stmt

        search_pattern = f"%{query.search}%"

        return stmt.where(
            or_(
                CareProviderModel.first_name.ilike(search_pattern),
                CareProviderModel.last_name.ilike(search_pattern),
                CareProviderModel.email.ilike(search_pattern),
                CareProviderModel.phone_number.ilike(search_pattern),
                CareProviderModel.code.ilike(search_pattern),
                CareProviderModel.care_provider_id.ilike(search_pattern),
            )
        )

   
    def _apply_role_filter(self, stmt: Select, query: CareProviderQuery) -> Select:
        """Apply role filter."""
        if query.role:
            stmt = stmt.where(CareProviderModel.role.in_(query.role))
        return stmt

    def _apply_ordering(self, stmt: Select, query: CareProviderQuery) -> Select:
        """Apply ordering to the query."""
        order_by = query.order_by or "created_at"
        is_desc = query.order and query.order.lower() == "desc"


        if order_by in self.ORDER_FIELDS:
            order_func = desc if is_desc else asc
            stmt = stmt.order_by(order_func(self.ORDER_FIELDS[order_by]))
        

        return stmt.order_by(desc(CareProviderModel.created_at))

    def _apply_pagination(
        self, stmt: Select, query: CareProviderQuery
    ) -> Select:
        """Apply pagination (offset and limit)."""
        if query.offset:
            stmt = stmt.offset(query.offset)
        if query.limit:
            stmt = stmt.limit(query.limit)
        return stmt

