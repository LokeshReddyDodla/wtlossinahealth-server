from typing import List, Literal, Optional
from pydantic import BaseModel


class PackageQuery(BaseModel):
    # pagination
    limit: Optional[int] = None
    offset: int = 0

    # scope (derived, not from client directly)
    health_facility_id: Optional[str] = None

    # filters (from query params)
    search: Optional[str] = None
    status: Optional[List[str]] = None
    type: Optional[List[str]] = None

    # sorting
    order_by: Optional[Literal["name", "duration_days", "price", "created_at"]] = "created_at"
    order: Literal["asc", "desc"] = "desc"

