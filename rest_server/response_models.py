from pydantic import BaseModel
from typing import Any, Generic, Optional, TypeVar

T = TypeVar("T")


class SuccessResponse(Generic[T], BaseModel):
    status: str = "success"
    data: Optional[T] = None
    message: Optional[str] = None


class ErrorResponse(Generic[T], BaseModel):
    status: str = "error"
    message: str
    detail: Optional[str] = None
