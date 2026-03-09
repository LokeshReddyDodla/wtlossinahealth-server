import asyncio
from typing import Optional

from lib.workers.tasks.patient_export.tasks import _enqueue_patient_export


async def enqueue_patient_export_async(export_id: str) -> Optional[str]:
    return await _enqueue_patient_export(export_id)


def enqueue_patient_export_sync(export_id: str) -> Optional[str]:
    import nest_asyncio

    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(enqueue_patient_export_async(export_id))
