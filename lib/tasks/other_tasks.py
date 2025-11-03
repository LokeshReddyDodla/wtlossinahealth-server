from celery import shared_task


@shared_task(queue="default")
async def process_smbg_batch(batch: list[dict]):
    try:
        from lib.dependencies.service_dependencies import (
            get_smbg_vector_service,
        )

        vector_service = get_smbg_vector_service()

        for smbg in batch:
            patient = smbg["patient"]
            if not patient:
                continue

            await vector_service.upsert_smbg(
                smbg["patient_id"],
                smbg["id"],
                smbg,
                patient["age"],
                patient["gender"],
            )

            print(
                f"✅ Stored SMBG {smbg['id']} for patient {smbg['patient_id']}"
            )

    except Exception as e:
        print(f"❌ Error processing batch: {e}")


@shared_task(queue="default")
async def process_profile_batch(batch: list[dict]):
    try:
        from lib.dependencies.service_dependencies import (
            get_patient_profile_vector_service,
        )

        vector_service = get_patient_profile_vector_service()

        for profile in batch:
            await vector_service.upsert_profile(
                profile,
            )

            print(f"✅ Stored Profile for patient {profile['patient_id']}")

    except Exception as e:
        print(f"❌ Error processing batch: {e}")
