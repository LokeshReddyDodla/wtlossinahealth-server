from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class SuccessResponse(BaseModel, Generic[T]):
    status: str = "success"
    data: Optional[T] = None
    message: Optional[str] = None


class ErrorResponse(BaseModel, Generic[T]):
    status: str = "error"
    message: str
    detail: Optional[str] = None


class InQueueResponse(BaseModel):
    status: str = "in_queue"  # or "pending", "processing"
    message: str
    data: Optional[Any] = None
