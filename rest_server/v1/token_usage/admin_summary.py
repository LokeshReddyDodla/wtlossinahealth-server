from datetime import date

from fastapi import Depends, Query

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import get_token_usage_service
from lib.services.token_usage_service import TokenUsageService
from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/admin/summary", response_model=SuccessResponse)
async def get_platform_usage_summary(
    start_date: date = Query(...),
    end_date: date = Query(...),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.ADMIN],
            check_permissions=False,
        )
    ),
    token_usage_service: TokenUsageService = Depends(get_token_usage_service),
):
    data = await token_usage_service.get_platform_usage_summary(
        start_date=start_date,
        end_date=end_date,
    )
    return SuccessResponse(message="Platform usage summary", data=data)
