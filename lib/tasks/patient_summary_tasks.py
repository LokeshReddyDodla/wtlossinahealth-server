from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from celery import shared_task

from lib.services.patient_summary.enum import RegeneratedBy
from lib.utils.timezone import get_ist_now


@shared_task(queue="default")
async def generate_yesterdays_daily_summary(patient_id: str) -> None:
    try:
        from lib.dependencies.service_dependencies import (
            get_patient_summary_service,
        )

        service = get_patient_summary_service()
        target_date = (get_ist_now() - timedelta(days=1)).date()
        print(f"==> target_date: {target_date}")

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
            f"✅ Scheduled yesterday's summaries for {len(patient_ids)} patients"
        )
    except Exception as e:
        print(f"❌ Failed to schedule daily summaries: {e}")


@shared_task(queue="default")
async def generate_daily_summary_for_patient(
    patient_id: str, target_date: date, forced: bool = False
) -> None:
    try:
        from lib.dependencies.service_dependencies import (
            get_patient_summary_service,
        )

        service = get_patient_summary_service()
        await service.generate_daily_summary(
            patient_id=patient_id,
            target_date=target_date,
            regenerated_by=RegeneratedBy.SYSTEM,
            forced=forced,
        )

        print(
            f"✅ Generated daily summary for {patient_id} on {target_date}"
        )
    except Exception as e:
        print(
            f"❌ Failed to generate daily summary for {patient_id} on {target_date}: {e}"
        )


@shared_task(queue="default")
async def generate_summaries_for_date(
    date_str: str, forced: bool = False, days: int = 3
) -> None:
    try:
        from lib.dependencies.service_dependencies import (
            get_active_patient_service,
        )

        # Parse the date string
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

        # Get active patients
        service = get_active_patient_service()
        patient_ids = await service.get_active_patients(days=days)

        # Queue summary generation for each patient
        for patient_id in patient_ids:
            generate_daily_summary_for_patient.delay(
                patient_id=patient_id,
                target_date=target_date,
                forced=forced,
            )

        print(
            f"✅ Scheduled summaries for {len(patient_ids)} patients on {target_date}"
        )
    except ValueError as e:
        print(
            f"❌ Invalid date format '{date_str}'. Expected YYYY-MM-DD format: {e}"
        )
    except Exception as e:
        print(f"❌ Failed to schedule summaries for date {date_str}: {e}")
