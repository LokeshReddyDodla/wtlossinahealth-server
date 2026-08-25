"""Live patient presence pushed to the care-provider dashboard over Socket.IO."""
import datetime
import logging

from uuid import UUID

from sqlalchemy import update

from lib.core.cache_store import CacheStore
from lib.core.constants import ProfileTypeEnum
from lib.dependencies.database import postgres_store
from lib.models.user_device import UserDevice
from lib.services.care_provider_access_service import CareProviderAccessService

logger = logging.getLogger(__name__)

_access_service = CareProviderAccessService(postgres_store)

# TTL so a leaked counter can't strand a patient "online" if a server dies
# before its disconnect fires.
_CONN_TTL_SECONDS = 24 * 3600

_cache = CacheStore("presence")


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _count(val) -> bool:
    try:
        return val is not None and int(val) > 0
    except (TypeError, ValueError):
        return False


async def is_online(patient_id: str) -> bool:
    """Online state from the connection counter; never raises."""
    try:
        return _count(await _cache.aget_key(f"conn:{patient_id}"))
    except Exception:
        return False


async def online_map(patient_ids: list[str]) -> dict[str, bool]:
    """Batch online lookup in one Redis round-trip."""
    if not patient_ids:
        return {}
    try:
        values = await _cache.amget_keys([f"conn:{pid}" for pid in patient_ids])
    except Exception:
        return {pid: False for pid in patient_ids}
    return {pid: _count(val) for pid, val in zip(patient_ids, values)}


def _room(patient_id: str) -> str:
    return f"presence:{patient_id}"


async def _accessible(care_provider_id: str, patient_ids: list[str]) -> list[str]:
    """Filter to patients this viewer may see — same facility/assignment scope
    the REST reads enforce. A presence room reads another user's state."""
    try:
        cp_uuid = UUID(str(care_provider_id))
        pid_uuids = [UUID(p) for p in patient_ids]
    except (TypeError, ValueError):
        return []
    async with postgres_store.get_session() as session:
        allowed = await _access_service.get_accessible_patients(
            care_provider_id=cp_uuid,
            patient_ids=pid_uuids,
            postgres_session=session,
        )
    return [str(p) for p in allowed]


async def subscribe(sio, sid, patient_ids: list[str]) -> None:
    """Join the presence rooms for the authorized subset and return their current
    state now, so presence is right on open, not only on the next transition."""
    ids = [str(p) for p in patient_ids if p]
    if not ids:
        return
    session = await sio.get_session(sid)
    user_id = session.get("user_id") if session else None
    role = session.get("role") if session else None
    if not user_id or role == ProfileTypeEnum.PATIENT.value:
        return
    ids = await _accessible(user_id, ids)
    for pid in ids:
        await sio.enter_room(sid, _room(pid))
    states = await online_map(ids)
    await sio.emit(
        "presence_bulk",
        [{"patient_id": pid, "online": online} for pid, online in states.items()],
        room=sid,
    )


async def unsubscribe(sio, sid, patient_ids: list[str]) -> None:
    for pid in patient_ids:
        if pid:
            await sio.leave_room(sid, _room(str(pid)))


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
    await sio.emit("presence", payload, room=_room(str(patient_id)))


async def patient_connected(sio, patient_id: str) -> None:
    """Emit online only on the first socket; every connect refreshes last_active_at."""
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
    """Emit offline only when the last socket closes; concurrent tabs stay online."""
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
