from pydantic import BaseModel
from typing import Any, Optional

class SuccessResponse(BaseModel):
    status: str = 'success'
    data: Optional[Any] = None
    message: Optional[str] = None
    
class ErrorResponse(BaseModel):
    status: str = 'error'
    message: str
    detail: Optional[str] = None