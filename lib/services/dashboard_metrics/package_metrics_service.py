from typing import List, Optional
from datetime import datetime
from sqlalchemy import Date, cast, func, select
from sqlalchemy.exc import SQLAlchemyError
from fastapi import status

from lib.dependencies.database import get_async_postgres_session
from lib.models.package import Package as PackageModel
from lib.utils.http_exceptions import raise_http_exception


class PackageMetricsService:
    async def get_packages_created_grouped_by_date(
        self,
        health_facility_id: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> List[dict]:
        try:
            async with get_async_postgres_session() as session:
                stmt = select(
                    cast(PackageModel.created_at, Date).label("date"),
                    func.count().label("count"),
                )

                if health_facility_id:
                    stmt = stmt.where(PackageModel.health_facility_id == health_facility_id)

                if start:
                    stmt = stmt.where(PackageModel.created_at >= start)
                if end:
                    stmt = stmt.where(PackageModel.created_at <= end)

                stmt = stmt.group_by(
                    cast(PackageModel.created_at, Date)
                ).order_by("date")

                result = await session.execute(stmt)

                return [
                    {"date": row.date.isoformat(), "count": row.count}
                    for row in result.all()
                ]

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to fetch packages count grouped by date",
                detail=str(e),
            )

