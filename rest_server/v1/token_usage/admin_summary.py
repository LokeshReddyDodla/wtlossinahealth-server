from datetime import date, datetime, time

from fastapi import Depends, Query

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import get_model_gateway
from lib.ai_foundation.models.gateway import ModelGateway
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
    gateway: ModelGateway = Depends(get_model_gateway),
):
    lf = gateway._langfuse_client
    if not lf:
        return SuccessResponse(
            message="Langfuse not configured",
            data={"daily": [], "by_model": []},
        )

    from_ts = datetime.combine(start_date, time.min)
    to_ts = datetime.combine(end_date, time.max)

    result = lf.api.metrics.daily(
        from_timestamp=from_ts,
        to_timestamp=to_ts,
        limit=100,
    )

    model_totals: dict[str, dict] = {}
    daily = []
    for day in result.data:
        total_input = sum(u.input_usage for u in day.usage)
        total_output = sum(u.output_usage for u in day.usage)
        daily.append({
            "date": day.date,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_cost": day.total_cost,
            "total_calls": day.count_observations,
        })
        for u in day.usage:
            key = u.model or "unknown"
            if key not in model_totals:
                model_totals[key] = {
                    "model": key,
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "total_cost": 0.0,
                    "total_calls": 0,
                }
            model_totals[key]["total_input_tokens"] += u.input_usage
            model_totals[key]["total_output_tokens"] += u.output_usage
            model_totals[key]["total_cost"] += u.total_cost
            model_totals[key]["total_calls"] += u.count_observations

    by_model = sorted(model_totals.values(), key=lambda m: m["total_cost"], reverse=True)

    return SuccessResponse(
        message="Platform usage summary",
        data={"daily": daily, "by_model": by_model},
    )
