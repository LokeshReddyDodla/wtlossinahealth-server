"""Detect clinically significant glucose threshold crossings on the latest
live-streamed CGM reading.

Deterministic signal detection. Produces *facts* — the LLM downstream
decides how to respond to them. No copy, no severity, no category here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel

from lib.services.clinical_constants import (
    CGM_LIVE_STREAM_FRESHNESS,
    GLUCOSE_HYPER_MGDL,
    GLUCOSE_HYPO_MGDL,
    GLUCOSE_RAPID_CHANGE_MGDL,
    GLUCOSE_RAPID_CHANGE_WINDOW,
    GLUCOSE_SEVERE_HYPER_MGDL,
    GLUCOSE_SEVERE_HYPO_MGDL,
)


class CGMCrossingKind(str, Enum):
    """The flavor of threshold the latest CGM reading crossed."""

    HYPO = "hypo"
    SEVERE_HYPO = "severe_hypo"
    HYPER = "hyper"
    SEVERE_HYPER = "severe_hyper"
    RAPID_SPIKE = "rapid_spike"
    RAPID_DROP = "rapid_drop"


class GlucoseCrossing(BaseModel):
    """One threshold crossing detected on a CGM reading."""

    kind: CGMCrossingKind
    value: int
    time: datetime


def _now_aligned(reference: datetime) -> datetime:
    """Return a current timestamp aware-aligned to ``reference``'s tzinfo."""
    if reference.tzinfo is None:
        return datetime.utcnow()
    return datetime.now(reference.tzinfo)


def detect_latest_crossing(rows: list[dict]) -> Optional[GlucoseCrossing]:
    """Return at most one threshold crossing for the freshest reading.

    Only the latest reading is evaluated so a long rolling-window sync
    (e.g. 12h of LibreLinkUp data) produces at most one event. Readings
    older than ``CGM_LIVE_STREAM_FRESHNESS`` are ignored, so CSV imports
    and backfills never trigger live alerts.

    Each row must have ``time`` (datetime) and ``glucose_level`` (numeric).
    """
    if not rows:
        return None

    fresh = [r for r in rows if isinstance(r.get("time"), datetime)]
    if not fresh:
        return None

    fresh.sort(key=lambda r: r["time"])
    latest = fresh[-1]

    if _now_aligned(latest["time"]) - latest["time"] > CGM_LIVE_STREAM_FRESHNESS:
        return None

    try:
        value = int(latest["glucose_level"])
    except (TypeError, ValueError):
        return None

    when: datetime = latest["time"]

    if value <= GLUCOSE_SEVERE_HYPO_MGDL:
        return GlucoseCrossing(kind=CGMCrossingKind.SEVERE_HYPO, value=value, time=when)
    if value < GLUCOSE_HYPO_MGDL:
        return GlucoseCrossing(kind=CGMCrossingKind.HYPO, value=value, time=when)
    if value >= GLUCOSE_SEVERE_HYPER_MGDL:
        return GlucoseCrossing(kind=CGMCrossingKind.SEVERE_HYPER, value=value, time=when)
    if value > GLUCOSE_HYPER_MGDL:
        return GlucoseCrossing(kind=CGMCrossingKind.HYPER, value=value, time=when)

    # Rapid change vs. nearest prior reading inside the window.
    for prior in reversed(fresh[:-1]):
        gap = when - prior["time"]
        if gap <= timedelta(0) or gap > GLUCOSE_RAPID_CHANGE_WINDOW:
            continue
        try:
            prior_value = int(prior["glucose_level"])
        except (TypeError, ValueError):
            continue
        delta = value - prior_value
        if delta >= GLUCOSE_RAPID_CHANGE_MGDL:
            return GlucoseCrossing(kind=CGMCrossingKind.RAPID_SPIKE, value=value, time=when)
        if delta <= -GLUCOSE_RAPID_CHANGE_MGDL:
            return GlucoseCrossing(kind=CGMCrossingKind.RAPID_DROP, value=value, time=when)
        break  # only compare against the nearest prior reading

    return None
