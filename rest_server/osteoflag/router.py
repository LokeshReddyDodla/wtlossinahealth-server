import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.service_dependencies import get_osteoflag_service
from lib.schemas.osteoflag import OsteoFlagDetectRequest
from lib.services.osteoflag_service import OsteoFlagService
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai/osteoflag", tags=["AI - OsteoFlag"])


@router.post("/screen", response_model=SuccessResponse)
@router.post("/screen-upload", response_model=SuccessResponse)
async def osteoflag_screen(
    request: Request,
    payload: OsteoFlagDetectRequest,
    osteoflag_service: OsteoFlagService = Depends(get_osteoflag_service),
    current_user=Depends(get_current_user),
):
    try:
        user_id, role = current_user
        user_type = None
        try:
            user_type = ProfileTypeEnum(role)
        except ValueError:
            user_type = None

        result = await osteoflag_service.detect(
            payload,
            user_id=user_id if user_type else None,
            user_type=user_type,
            api_endpoint=request.url.path,
        )

        return SuccessResponse(
            message="OsteoFlag detection completed.",
            data=result,
        )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as exc:
        logger.exception("OsteoFlag detection failed")
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Unable to complete detection. Please retry.",
            detail=str(exc),
        )
