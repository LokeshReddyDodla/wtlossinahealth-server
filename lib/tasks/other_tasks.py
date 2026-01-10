from datetime import datetime, timedelta

from celery import shared_task
from sqlalchemy import desc, func, update
from sqlalchemy.future import select

from lib.dependencies.database import get_async_postgres_session
from lib.models.user_device import UserDevice


@shared_task(queue="default")
async def deactivate_inactive_devices() -> None:
    """
    Weekly job to deactivate devices that have been inactive for more than 30 days.
    Keeps the 3 most recent devices active for each user, regardless of inactivity status.
    Marks all other inactive devices (more than 30 days) as is_active = False.
    """
    try:
        async with get_async_postgres_session() as session:
            # Calculate the cutoff date (30 days ago)
            cutoff_date = datetime.now().replace(tzinfo=None) - timedelta(days=30)
            
            # Get all users who have active devices
            # We need to process each user separately to keep their 3 most recent devices active
            stmt = (
                select(UserDevice.user_id)
                .where(UserDevice.is_active.is_(True))
                .distinct()
            )
            
            result = await session.execute(stmt)
            user_ids = [row[0] for row in result.all()]
            
            total_deactivated = 0
            users_processed = 0
            
            for user_id in user_ids:
                # Get all devices for this user, ordered by last_active_at (desc), then created_at (desc)
                # nullslast() puts devices with null last_active_at at the end
                user_devices_stmt = (
                    select(UserDevice)
                    .where(UserDevice.user_id == user_id, UserDevice.is_active.is_(True))
                    .order_by(
                        desc(UserDevice.last_active_at).nullslast(),
                        desc(UserDevice.created_at)
                    )
                )
                
                devices_result = await session.execute(user_devices_stmt)
                devices = list(devices_result.scalars().all())
                
                if not devices:
                    continue
                
                # Identify devices that are inactive for more than 30 days
                inactive_devices = []
                for device in devices:
                    is_inactive = (
                        device.last_active_at is None or
                        device.last_active_at < cutoff_date
                    )
                    if is_inactive:
                        inactive_devices.append(device)
                
                if not inactive_devices:
                    continue
                
                # Keep the 3 most recent devices active (regardless of inactivity)
                # These are already ordered by last_active_at desc, then created_at desc
                most_recent_device_ids = {device.device_id for device in devices[:3]}
                
                # Mark inactive devices as is_active = False, except for the 3 most recent
                devices_to_deactivate = [
                    device.device_id for device in inactive_devices
                    if device.device_id not in most_recent_device_ids
                ]
                
                if devices_to_deactivate:
                    update_stmt = (
                        update(UserDevice)
                        .where(UserDevice.device_id.in_(devices_to_deactivate))
                        .values(
                            is_active=False,
                            last_updated_at=datetime.now().replace(tzinfo=None)
                        )
                    )
                    await session.execute(update_stmt)
                    total_deactivated += len(devices_to_deactivate)
                    users_processed += 1
            
            await session.commit()
            
            print(
                f"✅ Deactivated {total_deactivated} inactive devices "
                f"for {users_processed} users (keeping 3 most recent active per user)"
            )
            
    except Exception as e:
        print(f"❌ Failed to deactivate inactive devices: {e}")
        import traceback
        traceback.print_exc()
        raise


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
