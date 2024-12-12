from typing import NoReturn

from fastapi import HTTPException, status

from rest_server.response_models import ErrorResponse


def raise_http_exception(
    status_code: int, message: str, detail: str = ""
) -> NoReturn:
    error_response = ErrorResponse(message=message, detail=detail)
    raise HTTPException(
        status_code=status_code, detail=error_response.model_dump()
    )
