import logging
from typing import NoReturn

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def raise_http_exception(status_code: int, message: str, detail: str = "") -> NoReturn:
    from rest_server.response_models import ErrorResponse

    logger.warning("http_exception status=%d message=%s detail=%s", status_code, message, detail)
    error_response = ErrorResponse(message=message, detail=detail)
    raise HTTPException(status_code=status_code, detail=error_response.model_dump())
