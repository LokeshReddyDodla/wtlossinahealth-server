from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel


class SleepStats(BaseModel):
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    duration_analysis: Dict[str, Any]
    type_distribution: Dict[str, Any]
    timing_analysis: Dict[str, Any]
    quality_analysis: Dict[str, Any]
    feedback: Optional[str] = None
