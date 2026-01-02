from typing import Optional, List, Literal
from pydantic import BaseModel

class PatientQuery(BaseModel):
    # view / intent
    mode: Literal["list", "dashboard"] = "list"

    # pagination
    limit: Optional[int] = None
    offset: int = 0

    # scope (derived, not from client directly)
    health_facility_id: Optional[str] = None
    care_provider_id: Optional[str] = None

    # filters (from query params)
    search: Optional[str] = None
    age: Optional[List[str]] = None
    gender: Optional[List[str]] = None
    monitoring_method: Optional[List[str]] = None
    package: Optional[List[str]] = None
    connected_apps: Optional[List[str]] = None

    # sorting
    order_by: Optional[Literal["first_name", "last_name", "email", "created_at", "dob", "age", "last_active_at"]] = "last_active_at"
    order: Literal["asc", "desc"] = "desc"

    # enrichment flags (API-driven)
    include_cgm: bool = False
    include_last_active: bool = False
