import asyncio
from datetime import date
from typing import Any, Dict

from celery import shared_task


@shared_task
async def generate_daily_meal_report(
    patient_id: str,
    report_date: date,
):
    try:
        from lib.dependencies.service_dependencies import (
            get_meal_report_service,
            get_meal_stats_processor,
        )

        processor = get_meal_stats_processor()
        service = get_meal_report_service()

        # Generate the meal report
        report = await processor.get_meal_report_by_date(
            patient_id, report_date
        )

        # Save the meal report
        await service.save_report(
            patient_id,
            {
                "patient_id": patient_id,
                "report_type": "daily",
                **report.model_dump(),
            },
        )

        print(
            f"✅ Successfully generated meal report for {patient_id} on {report_date}"
        )

    except Exception as error:
        print(
            f"❌ Failed to generate meal report for {patient_id} on {report_date}. Error: {error}"
        )


@shared_task
async def generate_meal_vector(
    patient_id: str, meal_id: str, meal_data: dict[str, Any]
):
    try:
        from lib.dependencies.service_dependencies import (
            get_meal_vector_service,
            get_patient_profile_service,
        )

        vector_service = get_meal_vector_service()
        patient_service = get_patient_profile_service()

        patient_profile = await patient_service.fetch_patient_profile(
            patient_id
        )
        if not patient_profile:
            print(f"⚠️ Patient profile not found for {patient_id}")
            return

        await vector_service.upsert_meal(
            patient_id,
            meal_id,
            meal_data,
            patient_profile.age,
            patient_profile.gender,
        )

        print(f"✅ Successfully generated Meal vector for {patient_id}")

    except Exception as error:
        print(f"❌ Failed to generate Meal vector for {patient_id}: {error}")


@shared_task
async def process_meal_batch(batch: list[dict]):
    try:
        from lib.dependencies.service_dependencies import (
            get_meal_vector_service,
        )

        vector_service = get_meal_vector_service()

        for meal in batch:
            patient = meal["patient"]
            patient_id = meal["patient_id"]

            await vector_service.upsert_meal(
                patient_id,
                meal["id"],
                meal,
                patient["age"],
                patient["gender"],
            )

            print(f"✅ Stored meal {meal['id']} for patient {patient_id}")

    except Exception as e:
        print(f"❌ Error processing batch: {e}")
