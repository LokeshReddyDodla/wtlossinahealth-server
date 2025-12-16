from __future__ import annotations

from datetime import datetime, timedelta, timezone

from celery import shared_task

from lib.services.patient_summary.enum import RegeneratedBy


@shared_task(queue="default")
async def generate_yesterdays_daily_summary(patient_id: str) -> None:
    try:
        from lib.dependencies.service_dependencies import (
            get_patient_summary_service,
        )

        service = get_patient_summary_service()
        target_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()

        await service.generate_daily_summary(
            patient_id=patient_id,
            target_date=target_date,
            regenerated_by=RegeneratedBy.SYSTEM,
        )

        print(
            f"✅ Generated yesterday’s daily summary for {patient_id} ({target_date})"
        )
    except Exception as e:
        print(
            f"❌ Failed to generate yesterday’s summary for {patient_id}: {e}"
        )


@shared_task(queue="default")
async def schedule_daily_patient_summaries() -> None:
    try:
        from lib.dependencies.service_dependencies import (
            get_active_patient_service,
        )

        service = get_active_patient_service()
        patient_ids = await service.get_active_patients(days=3)

        for patient_id in patient_ids:
            generate_yesterdays_daily_summary.delay(patient_id)

        print(
            f"✅ Scheduled yesterday’s summaries for {len(patient_ids)} patients"
        )
    except Exception as e:
        print(f"❌ Failed to schedule daily summaries: {e}")
