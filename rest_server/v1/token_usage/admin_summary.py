import logging
from datetime import date, datetime, time

from fastapi import Depends, Query

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import get_model_gateway, get_patient_profile_service
from lib.ai_foundation.models.gateway import ModelGateway
from lib.services.patient_profile_service import PatientProfileService
from rest_server.response_models import SuccessResponse

from .router import router

logger = logging.getLogger(__name__)


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


@router.get("/admin/by-patient", response_model=SuccessResponse)
async def get_usage_by_patient(
    start_date: date = Query(...),
    end_date: date = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str = Query("", description="Search by name or user_id"),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.ADMIN],
            check_permissions=False,
        )
    ),
    gateway: ModelGateway = Depends(get_model_gateway),
    patient_service: PatientProfileService = Depends(get_patient_profile_service),
):
    lf = gateway._langfuse_client
    if not lf:
        return SuccessResponse(message="Langfuse not configured", data={
            "patients": [], "total": 0, "page": page, "page_size": page_size, "total_cost": 0,
        })

    from_ts = datetime.combine(start_date, time.min)
    to_ts = datetime.combine(end_date, time.max)

    user_agg: dict[str, dict] = {}
    lf_page = 1
    while True:
        resp = lf.fetch_traces(
            from_timestamp=from_ts,
            to_timestamp=to_ts,
            limit=100,
            page=lf_page,
        )
        for trace in resp.data:
            uid = trace.user_id
            if not uid:
                continue
            if uid not in user_agg:
                user_agg[uid] = {"user_id": uid, "total_cost": 0.0, "total_traces": 0}
            user_agg[uid]["total_cost"] += trace.total_cost
            user_agg[uid]["total_traces"] += 1

        if lf_page * resp.meta.limit >= resp.meta.total_items:
            break
        lf_page += 1

    patient_ids = list(user_agg.keys())
    profiles = await patient_service.fetch_patient_profiles(patient_ids) if patient_ids else {}

    all_rows = []
    platform_cost = 0.0
    for uid, agg in user_agg.items():
        profile = profiles.get(uid)
        name = None
        if profile:
            name = " ".join(filter(None, [profile.first_name, profile.last_name])) or None
        platform_cost += agg["total_cost"]
        all_rows.append({
            "user_id": uid,
            "name": name,
            "total_cost": round(agg["total_cost"], 6),
            "total_traces": agg["total_traces"],
        })

    all_rows.sort(key=lambda r: r["total_cost"], reverse=True)

    search = q.strip().lower()
    if search:
        all_rows = [
            r for r in all_rows
            if search in (r["name"] or "").lower() or search in r["user_id"].lower()
        ]

    total = len(all_rows)
    start = (page - 1) * page_size
    patients = all_rows[start : start + page_size]

    return SuccessResponse(message="Usage by patient", data={
        "patients": patients,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_cost": round(platform_cost, 2),
    })
