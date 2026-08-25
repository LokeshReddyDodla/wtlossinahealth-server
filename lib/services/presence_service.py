"""Live patient presence for the care-provider dashboard.

Presence is derived from the Socket.IO connection the patient app already
holds: a patient with an open socket is online, and the last disconnect stamps
last_active_at. Connections are counted in Redis so multiple tabs/devices read
as one presence and the count is correct across API instances. Each change is
pushed to the patient's care providers over the socket room they already
occupy (keyed by care_provider_id).
"""
import datetime
import logging

from sqlalchemy import select, update

from lib.core.cache_store import CacheStore
from lib.core.constants import ProfileTypeEnum
from lib.dependencies.database import postgres_store
from lib.models.associations import patient_care_provider_association
from lib.models.user_device import UserDevice

logger = logging.getLogger(__name__)

# Safety TTL so a leaked counter can never strand a patient "online" forever if
# a server dies before its disconnect fires. The dashboard's own staleness
# fallback is the second line of defence.
_CONN_TTL_SECONDS = 24 * 3600

_cache = CacheStore("presence")


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


async def _care_provider_rooms(patient_id: str) -> list[str]:
    async with postgres_store.get_session() as session:
        result = await session.execute(
            select(patient_care_provider_association.c.care_provider_id).where(
                patient_care_provider_association.c.patient_id == patient_id
            )
        )
        return [str(cp_id) for (cp_id,) in result.all()]


async def _stamp_last_active(patient_id: str, ts: datetime.datetime) -> None:
    # ponytail: the socket handshake carries no device id, so bump every one of
    # the patient's devices — the dashboard reads max(last_active_at) and only
    # cares about the patient, not which device. Add x-device-id to the socket
    # query if the per-device view ever needs precise attribution.
    async with postgres_store.get_session() as session:
        await session.execute(
            update(UserDevice)
            .where(
                UserDevice.user_id == patient_id,
                UserDevice.profile_type == ProfileTypeEnum.PATIENT.value,
            )
            .values(last_active_at=ts)
        )
        await session.commit()


async def _emit(sio, patient_id: str, online: bool, ts: datetime.datetime) -> None:
    payload = {
        "patient_id": str(patient_id),
        "online": online,
        "last_active_at": ts.isoformat(),
    }
    for room in await _care_provider_rooms(patient_id):
        await sio.emit("presence", payload, room=room)


async def patient_connected(sio, patient_id: str) -> None:
    """The first live socket flips the patient online; every connect refreshes
    last_active_at so the dashboard is current without waiting for a REST call."""
    try:
        count = await _cache.aincr_key(f"conn:{patient_id}")
        await _cache.aexpire_key(f"conn:{patient_id}", _CONN_TTL_SECONDS)
        ts = _now()
        await _stamp_last_active(patient_id, ts)
        if count == 1:
            await _emit(sio, patient_id, True, ts)
    except Exception:
        logger.exception("presence connect failed for patient=%s", patient_id)


async def patient_disconnected(sio, patient_id: str) -> None:
    """The last socket closing flips the patient offline and stamps the leave
    time. Concurrent tabs keep them online until every one is gone."""
    try:
        count = await _cache.adecr_key(f"conn:{patient_id}")
        if count > 0:
            return
        await _cache.adelete_key(f"conn:{patient_id}")
        ts = _now()
        await _stamp_last_active(patient_id, ts)
        await _emit(sio, patient_id, False, ts)
    except Exception:
        logger.exception("presence disconnect failed for patient=%s", patient_id)
