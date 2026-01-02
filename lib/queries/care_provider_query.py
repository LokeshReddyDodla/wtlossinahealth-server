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
    order_by: Optional[Literal["name", "role", "created_at", "is_verified"]] = "created_at"
    order: Literal["asc", "desc"] = "desc"

