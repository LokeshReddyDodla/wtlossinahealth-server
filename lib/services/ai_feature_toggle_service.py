"""Runtime pause/resume for AI features (system-wide or per health facility).

Design notes:
- Opt-out model: the table holds only *disabled* rows. Absence = enabled.
- The read path runs on every chat/push/meal, so it must not hit the DB per
  call. The whole toggle set is tiny (default-on means only exceptions are
  stored), so we hold it in an in-process snapshot refreshed on a short TTL.
  The per-request check is an in-memory set lookup — zero I/O.
- Fail-open: if the DB read fails we keep serving on the last-known-good
  snapshot (a cache blip must not take down every AI surface). Only a positive
  "disabled" read ever pauses anything.
- Propagation across worker processes is TTL-bounded (a flip is visible
  everywhere within SNAPSHOT_TTL_SECONDS). The process that writes busts its
  own snapshot immediately.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Iterable, Optional
from uuid import UUID

from sqlalchemy import select

from lib.core.constants import AIFeatureEnum, AIToggleScopeEnum
from lib.dependencies.database import get_async_postgres_session
from lib.models.ai_feature_toggle import AIFeatureToggle
from lib.models.patient import Patient
from lib.utils.http_exceptions import raise_http_exception

SNAPSHOT_TTL_SECONDS = 15.0
_UNAVAILABLE_MESSAGE = (
    "This AI feature is temporarily unavailable. Please try again later."
)


@dataclass
class _Snapshot:
    system_disabled: set[str]  # features off globally
    facility_disabled: dict[str, set[str]]  # feature -> facility_ids off
    loaded_at: float


def _feature_value(feature: AIFeatureEnum | str) -> str:
    return feature.value if isinstance(feature, AIFeatureEnum) else str(feature)


class AIFeatureToggleService:
    def __init__(self) -> None:
        self._snapshot: Optional[_Snapshot] = None
        self._lock = asyncio.Lock()

    # ── snapshot ─────────────────────────────────────────────────────────

    async def _get_snapshot(self) -> _Snapshot:
        snap = self._snapshot
        if snap is not None and (time.monotonic() - snap.loaded_at) < SNAPSHOT_TTL_SECONDS:
            return snap
        async with self._lock:
            snap = self._snapshot
            if snap is not None and (time.monotonic() - snap.loaded_at) < SNAPSHOT_TTL_SECONDS:
                return snap
            try:
                self._snapshot = await self._load()
            except Exception:
                # Fail open: keep last-known-good; if we never loaded, treat all
                # features as enabled rather than block everything on a DB blip.
                if self._snapshot is None:
                    self._snapshot = _Snapshot(set(), {}, time.monotonic())
                else:
                    self._snapshot.loaded_at = time.monotonic()
            return self._snapshot

    async def _load(self) -> _Snapshot:
        async with get_async_postgres_session() as session:
            rows = (
                await session.execute(
                    select(AIFeatureToggle).where(AIFeatureToggle.enabled.is_(False))
                )
            ).scalars().all()

        system_disabled: set[str] = set()
        facility_disabled: dict[str, set[str]] = {}
        for row in rows:
            if row.scope == AIToggleScopeEnum.SYSTEM.value:
                system_disabled.add(row.feature)
            elif row.scope == AIToggleScopeEnum.FACILITY.value and row.scope_id:
                facility_disabled.setdefault(row.feature, set()).add(str(row.scope_id))
        return _Snapshot(system_disabled, facility_disabled, time.monotonic())

    # ── checks ───────────────────────────────────────────────────────────

    async def is_enabled(
        self, feature: AIFeatureEnum | str, *, facility_id: Optional[str] = None
    ) -> bool:
        feat = _feature_value(feature)
        snap = await self._get_snapshot()
        if feat in snap.system_disabled:
            return False
        if facility_id is not None:
            disabled = snap.facility_disabled.get(feat)
            if disabled and str(facility_id) in disabled:
                return False
        return True

    async def _facility_overrides_exist(self, feature: AIFeatureEnum | str) -> bool:
        snap = await self._get_snapshot()
        return bool(snap.facility_disabled.get(_feature_value(feature)))

    async def _facility_for_patient(self, patient_id: str) -> Optional[str]:
        async with get_async_postgres_session() as session:
            fid = (
                await session.execute(
                    select(Patient.health_facility_id).where(
                        Patient.patient_id == patient_id
                    )
                )
            ).scalar_one_or_none()
        return str(fid) if fid else None

    async def is_enabled_for_patient(
        self, feature: AIFeatureEnum | str, patient_id: Optional[str]
    ) -> bool:
        """System check always; facility check only when some facility has
        paused this feature (rare) — avoids a patient->facility lookup on the
        common path."""
        if not await self.is_enabled(feature):
            return False
        if patient_id and await self._facility_overrides_exist(feature):
            facility_id = await self._facility_for_patient(patient_id)
            return await self.is_enabled(feature, facility_id=facility_id)
        return True

    # ── guards (raise 503 when paused) ─────────────────────────────────────

    async def require_system(self, feature: AIFeatureEnum | str) -> None:
        if not await self.is_enabled(feature):
            raise_http_exception(status_code=503, message=_UNAVAILABLE_MESSAGE)

    async def require_facility(
        self, feature: AIFeatureEnum | str, facility_id: Optional[str]
    ) -> None:
        if not await self.is_enabled(feature, facility_id=facility_id):
            raise_http_exception(status_code=503, message=_UNAVAILABLE_MESSAGE)

    async def require_for_patients(
        self, feature: AIFeatureEnum | str, patient_ids: Iterable[str]
    ) -> None:
        ids = [pid for pid in (patient_ids or []) if pid]
        # Facility scope is unambiguous only for a single patient; multi-patient
        # (provider/admin) queries are gated at system level only.
        single = ids[0] if len(ids) == 1 else None
        if not await self.is_enabled_for_patient(feature, single):
            raise_http_exception(status_code=503, message=_UNAVAILABLE_MESSAGE)

    # ── admin writes / reads ───────────────────────────────────────────────

    async def set_toggle(
        self,
        *,
        feature: str,
        scope: str,
        scope_id: Optional[UUID],
        enabled: bool,
        reason: Optional[str],
        admin_id: Optional[UUID],
    ) -> None:
        async with get_async_postgres_session() as session:
            stmt = select(AIFeatureToggle).where(
                AIFeatureToggle.scope == scope,
                AIFeatureToggle.feature == feature,
            )
            stmt = (
                stmt.where(AIFeatureToggle.scope_id.is_(None))
                if scope_id is None
                else stmt.where(AIFeatureToggle.scope_id == scope_id)
            )
            existing = (await session.execute(stmt)).scalars().first()
            if existing:
                existing.enabled = enabled
                existing.reason = reason
                existing.updated_by = admin_id
            else:
                session.add(
                    AIFeatureToggle(
                        scope=scope,
                        scope_id=scope_id,
                        feature=feature,
                        enabled=enabled,
                        reason=reason,
                        updated_by=admin_id,
                    )
                )
            await session.commit()
        self._snapshot = None  # bust this process immediately; others refresh on TTL

    async def get_overrides(self) -> list[dict]:
        async with get_async_postgres_session() as session:
            rows = (
                await session.execute(select(AIFeatureToggle))
            ).scalars().all()
        return [
            {
                "feature": r.feature,
                "scope": r.scope,
                "scope_id": str(r.scope_id) if r.scope_id else None,
                "enabled": r.enabled,
                "reason": r.reason,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]


ai_feature_toggle_service = AIFeatureToggleService()


def actor_facility_id(actor: object) -> Optional[str]:
    """Facility id off an Actor's loaded model (patient/care_provider carry
    health_facility_id; admin has none -> None -> system-level check only)."""
    fid = getattr(getattr(actor, "model", None), "health_facility_id", None)
    return str(fid) if fid else None
