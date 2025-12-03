from typing import Any, Dict, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

from lib.core.constants import API_RESPONSE_VERSION

T = TypeVar("T")


class SuccessResponse(BaseModel, Generic[T]):
    status: str = "success"
    version: str = Field(default=API_RESPONSE_VERSION)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    data: Optional[T] = None
    message: Optional[str] = None


class ErrorResponse(BaseModel, Generic[T]):
    status: str = "error"
    version: str = Field(default=API_RESPONSE_VERSION)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    message: str
    detail: Optional[str] = None


class InQueueResponse(BaseModel):
    status: str = "in_queue"  # or "pending", "processing"
    version: str = Field(default=API_RESPONSE_VERSION)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    message: str
    data: Optional[Any] = None
