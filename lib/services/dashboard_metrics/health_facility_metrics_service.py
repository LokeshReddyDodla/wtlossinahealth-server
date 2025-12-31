from typing import List, Optional
from datetime import datetime
from sqlalchemy import Date, cast, func, select
from sqlalchemy.exc import SQLAlchemyError
from fastapi import status

from lib.dependencies.database import get_async_postgres_session
from lib.models.health_facility import HealthFacility as HealthFacilityModel
from lib.utils.http_exceptions import raise_http_exception


class HealthFacilityMetricsService:
    async def get_health_facilities_onboarded_grouped_by_date(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> List[dict]:
        try:
            async with get_async_postgres_session() as session:
                stmt = select(
                    cast(HealthFacilityModel.created_at, Date).label("date"),
                    func.count().label("count"),
                )

                if start:
                    stmt = stmt.where(HealthFacilityModel.created_at >= start)
                if end:
                    stmt = stmt.where(HealthFacilityModel.created_at <= end)

                stmt = stmt.group_by(
                    cast(HealthFacilityModel.created_at, Date)
                ).order_by("date")

                result = await session.execute(stmt)

                return [
                    {"date": row.date.isoformat(), "count": row.count}
                    for row in result.all()
                ]

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch health facilities count grouped by date",
                detail=str(e),
            )

