"""
Outcome loop — Postgres-backed advice ledger that tracks whether nudges work.

ADVISE -> LOG (write the event BEFORE delivery)
       -> FOLLOW-UP (fetch CGM around the advised meal, compute observed delta)
       -> ROLL UP (per trigger: compliance rate, predicted vs observed delta, efficacy).

Track-agnostic: works for "glucose" (outcome = spike change, mg/dL) and "obesity"
(outcome = weight/body-composition change, %).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, func, case, and_

from lib.core.postgres_store import PostgresStore
from lib.models.clinical_outcome import AdviceEvent, AdviceFollowup, ClinicalDecisionAudit

from lib.ai_foundation.config import settings

logger = logging.getLogger(__name__)


class OutcomeRepository:
    """Postgres-backed outcome tracking. Injected into MetabolicService."""

    def __init__(self, postgres_store: PostgresStore) -> None:
        self._pg = postgres_store

    async def log_advice(self, event: dict[str, Any]) -> UUID:
        """Insert an advice event BEFORE delivery. Returns the event ID."""
        async with self._pg.get_session() as session:
            row = AdviceEvent(
                patient_id=event["patient_id"],
                track=event.get("track", "glucose"),
                trigger=event.get("trigger", "meal"),
                meal_slot=event.get("meal_slot"),
                output_mode=event.get("output_mode", "SUGGEST"),
                lever_name=event.get("lever_name"),
                lever_say=event.get("move"),
                predicted_delta=event.get("predicted_delta"),
                cite=event.get("cite"),
                confidence=event.get("confidence"),
                meal_macros=event.get("meal_macros"),
                meal_time=event.get("meal_time"),
                contract_snapshot=event.get("contract_snapshot"),
            )
            session.add(row)
            await session.commit()
            logger.info("advice logged: patient=%s lever=%s delta=%s",
                        event["patient_id"], event.get("lever_name"), event.get("predicted_delta"))
            return row.id

    async def get_pending_followups(
        self,
        patient_id: str | UUID,
        min_age_hours: float | None = None,
        max_age_days: int | None = None,
    ) -> list[AdviceEvent]:
        """Find advice events ready for follow-up: old enough for CGM, not yet followed up."""
        if min_age_hours is None:
            min_age_hours = settings.METABOLIC_FOLLOWUP_WINDOW_HOURS
        if max_age_days is None:
            max_age_days = settings.METABOLIC_FOLLOWUP_MAX_AGE_DAYS
        now = datetime.now(timezone.utc)
        cutoff_min = now - timedelta(hours=min_age_hours)
        cutoff_max = now - timedelta(days=max_age_days)
        async with self._pg.get_session() as session:
            result = await session.execute(
                select(AdviceEvent)
                .where(
                    AdviceEvent.patient_id == str(patient_id),
                    AdviceEvent.followed_up == False,  # noqa: E712
                    AdviceEvent.meal_time.isnot(None),
                    AdviceEvent.meal_time <= cutoff_min,
                    AdviceEvent.meal_time >= cutoff_max,
                )
                .order_by(AdviceEvent.logged_at.desc())
                .limit(10)
            )
            return list(result.scalars().all())

    async def record_followup(
        self,
        event_id: UUID,
        *,
        complied: bool | None = None,
        observed_delta: float | None = None,
        evidence: str | None = None,
        followup_meal_macros: dict | None = None,
        cgm_pre: float | None = None,
        cgm_peak: float | None = None,
    ) -> None:
        """Record the follow-up for an advice event."""
        outcome = "unknown"
        if complied and observed_delta is not None:
            # predicted_delta < 0 means "should drop"
            async with self._pg.get_session() as session:
                event = await session.get(AdviceEvent, event_id)
                if event and event.predicted_delta is not None:
                    same_dir = (observed_delta <= 0) == (event.predicted_delta <= 0)
                    outcome = "as_predicted" if same_dir else "opposite"

        async with self._pg.get_session() as session:
            followup = AdviceFollowup(
                event_id=event_id,
                complied=complied,
                compliance_evidence=evidence,
                observed_delta=observed_delta,
                outcome_vs_predicted=outcome if complied else None,
                followup_meal_macros=followup_meal_macros,
                cgm_pre=cgm_pre,
                cgm_peak=cgm_peak,
            )
            session.add(followup)
            # mark the event as followed up
            event = await session.get(AdviceEvent, event_id)
            if event:
                event.followed_up = True
            await session.commit()
            logger.info("followup recorded: event=%s complied=%s delta=%s outcome=%s",
                        event_id, complied, observed_delta, outcome)

    async def rollup(self, valid_floor: int = 10) -> list[dict[str, Any]]:
        """Aggregate efficacy stats per (track, trigger)."""
        async with self._pg.get_session() as session:
            # join events with followups
            q = (
                select(
                    AdviceEvent.track,
                    AdviceEvent.trigger,
                    func.count(AdviceEvent.id).label("advices"),
                    func.count(AdviceFollowup.id).label("followed"),
                    func.sum(case((AdviceFollowup.complied == True, 1), else_=0)).label("complied"),  # noqa: E712
                    func.sum(case(
                        (and_(AdviceFollowup.complied == True,  # noqa: E712
                              AdviceFollowup.observed_delta.isnot(None)), 1),
                        else_=0,
                    )).label("with_outcome"),
                    func.avg(case(
                        (AdviceFollowup.complied == True, AdviceFollowup.observed_delta),  # noqa: E712
                        else_=None,
                    )).label("mean_obs"),
                    func.avg(case(
                        (AdviceFollowup.complied == True, AdviceEvent.predicted_delta),  # noqa: E712
                        else_=None,
                    )).label("mean_pred"),
                    func.sum(case(
                        (AdviceFollowup.outcome_vs_predicted == "as_predicted", 1),
                        else_=0,
                    )).label("as_pred"),
                )
                .outerjoin(AdviceFollowup, AdviceFollowup.event_id == AdviceEvent.id)
                .group_by(AdviceEvent.track, AdviceEvent.trigger)
                .order_by(AdviceEvent.track, AdviceEvent.trigger)
            )
            result = await session.execute(q)
            rows = result.all()

        out = []
        for row in rows:
            n_outcome = int(row.with_outcome or 0)
            n_followed = int(row.followed or 0)
            n_complied = int(row.complied or 0)
            out.append({
                "track": row.track,
                "trigger": row.trigger,
                "advices": int(row.advices),
                "compliance_rate": round(n_complied / n_followed, 2) if n_followed else None,
                "n_with_outcome": n_outcome,
                "mean_predicted_delta": round(float(row.mean_pred), 1) if row.mean_pred else None,
                "mean_observed_delta": round(float(row.mean_obs), 1) if row.mean_obs else None,
                "moved_as_predicted_pct": round(100 * int(row.as_pred) / n_outcome) if n_outcome else None,
                "valid": n_outcome >= valid_floor,
            })
        return out

    async def log_decision(self, patient_id: str | UUID, contract: dict, trace_id: str | None = None) -> None:
        """Append an immutable clinical decision audit record."""
        pr = contract.get("prediction") or {}
        attr = contract.get("attribution") or {}
        v31 = contract.get("v31") or {}
        async with self._pg.get_session() as session:
            session.add(ClinicalDecisionAudit(
                patient_id=str(patient_id),
                trace_id=trace_id,
                output_mode=contract.get("output_mode", ""),
                safety_flags=contract.get("safety_flags"),
                attribution_label=attr.get("label"),
                confidence=pr.get("confidence"),
                rise_mgdl=pr.get("rise_mgdl"),
                has_cgm=v31.get("has_cgm"),
                lever_name=(contract.get("lever") or {}).get("name"),
                contract_snapshot=contract,
            ))
            await session.commit()


# -- Pure function: maps engine contract to advice event dict (no DB) --

def advice_event_from_contract(
    contract: dict,
    patient_id: str,
    track: str,
    trigger: str,
    meal_slot: str | None = None,
    meal_macros: dict | None = None,
    meal_time: datetime | None = None,
) -> dict[str, Any] | None:
    """Map an engine contract to an advice event dict. Returns None for non-SUGGEST.

    Only a cited SUGGEST is logged (Forge P1).
    """
    if track == "glucose":
        if contract.get("output_mode") != "SUGGEST":
            return None
        lever = contract.get("lever") or {}
        cite = lever.get("cite")
        if not cite:
            return None
        return {
            "patient_id": patient_id,
            "track": track,
            "trigger": trigger,
            "meal_slot": meal_slot,
            "output_mode": "SUGGEST",
            "lever_name": lever.get("name"),
            "move": lever.get("say"),
            "predicted_delta": lever.get("effect_mgdl"),
            "cite": cite,
            "confidence": (contract.get("prediction") or {}).get("confidence"),
            "meal_macros": meal_macros,
            "meal_time": meal_time,
            "contract_snapshot": contract,
        }
    else:  # obesity
        b = contract.get("bmiq") or {}
        if b.get("output_mode") != "SUGGEST":
            return None
        lv = b.get("lever") or {}
        cite = lv.get("cite")
        if not cite:
            return None
        return {
            "patient_id": patient_id,
            "track": track,
            "trigger": trigger,
            "output_mode": "SUGGEST",
            "lever_name": lv.get("name") or lv.get("priority"),
            "move": lv.get("name") or lv.get("priority"),
            "predicted_delta": lv.get("effect_pct"),
            "cite": cite,
            "confidence": (contract.get("prediction") or {}).get("confidence"),
            "contract_snapshot": contract,
        }
