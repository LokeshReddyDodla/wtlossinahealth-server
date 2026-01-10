from typing import List, Literal, Optional
from pydantic import BaseModel

class CareProviderQuery(BaseModel):
    # pagination
    limit: Optional[int] = None
    offset: int = 0

    # scope (derived, not from client directly)
    health_facility_id: Optional[str] = None

    # filters (from query params)
    search: Optional[str] = None
    role: Optional[List[str]] = None

    # sorting
    order_by: Optional[Literal["first_name", "last_name", "email", "role", "created_at", "is_verified", "last_active_at"]] = "created_at"
    order: Literal["asc", "desc"] = "desc"

