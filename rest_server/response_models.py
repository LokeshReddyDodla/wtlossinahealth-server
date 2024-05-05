from pydantic import BaseModel
from typing import Any, Optional

class SuccessResponse(BaseModel):
    success: bool = True
    data: Optional[Any] = None
    message: Optional[str] = None
    
class ErrorResponse(BaseModel):
    success: bool = False
    message: str
    detail: Optional[str] = None