"""Clinical threshold constants — shared across CGM detection, patient
summary, proactive monitor, and any other module that needs them.

Centralized so a change in evidence-based defaults is a one-file edit.
"""

from __future__ import annotations

from datetime import timedelta


# ── Glucose (mg/dL) ─────────────────────────────────────────────────────
# ADA standard ranges.

GLUCOSE_HYPO_MGDL: int = 70
GLUCOSE_SEVERE_HYPO_MGDL: int = 54
GLUCOSE_HYPER_MGDL: int = 180
GLUCOSE_SEVERE_HYPER_MGDL: int = 250

# Rapid change between consecutive readings.
GLUCOSE_RAPID_CHANGE_MGDL: int = 30
GLUCOSE_RAPID_CHANGE_WINDOW: timedelta = timedelta(minutes=20)

# Don't alert on backfilled / CSV-imported data older than this.
CGM_LIVE_STREAM_FRESHNESS: timedelta = timedelta(minutes=30)
