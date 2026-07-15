from datetime import datetime
from typing import Optional

from fastapi import Depends, status
from pydantic import BaseModel

from lib.core.clickhouse_store import get_clickhouse_store
from lib.dependencies.auth.admin_auth import get_current_admin
from lib.models.admin import Admin
from lib.utils.date_utils import get_months_between_dates
from lib.utils.http_exceptions import raise_http_exception
from lib.workers.arq.config import Queues
from lib.workers.arq.redis import enqueue_job
from rest_server.response_models import SuccessResponse

from .router import router


class RegenerateRequest(BaseModel):
    patient_id: Optional[str] = None
    start_date: datetime
    end_date: datetime


@router.post("/fitness/regenerate", response_model=SuccessResponse)
async def regenerate_fitness_reports(
    body: RegenerateRequest,
    current_admin: Admin = Depends(get_current_admin),
):
    try:
        months = get_months_between_dates(body.start_date, body.end_date)
        if not months:
            return SuccessResponse(
                message="No months in the given date range",
                data={"enqueued": 0},
            )

        if body.patient_id:
            patient_ids = [body.patient_id]
        else:
            ch = get_clickhouse_store()
            rows = ch.client.execute(
                "SELECT DISTINCT patient_id FROM aihealth.fitness_data "
                "WHERE start_datetime >= %(start)s AND start_datetime <= %(end)s",
                {"start": body.start_date, "end": body.end_date},
            )
            patient_ids = [r[0] for r in rows]

        if not patient_ids:
            return SuccessResponse(
                message="No patients with fitness data in this range",
                data={"enqueued": 0},
            )

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        enqueued = []
        for pid in patient_ids:
            job_id = f"fitness:regen:{pid}:{timestamp}"
            job = await enqueue_job(
                "force_regenerate_fitness_reports",
                pid,
                body.start_date,
                body.end_date,
                _job_id=job_id,
                _queue_name=Queues.REPORTS,
            )
            if job:
                enqueued.append(pid)

        return SuccessResponse(
            message=f"Enqueued fitness report regeneration for {len(enqueued)} patients x {len(months)} months",
            data={
                "patients": len(enqueued),
                "months": len(months),
                "start_date": body.start_date.isoformat(),
                "end_date": body.end_date.isoformat(),
            },
        )

    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to enqueue report regeneration",
            detail=str(e),
        )
