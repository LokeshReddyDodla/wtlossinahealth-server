from typing import Any, Dict, List

from pydantic import BaseModel, Field

from rest_server.response_models import SuccessResponse


class FitnessReportListResponse(BaseModel):
    reports: List[Dict[str, Any]] = Field(..., description="List of fitness reports")
    total: int = Field(..., description="Total number of reports")


ListFitnessReportsResponse = SuccessResponse[FitnessReportListResponse]
