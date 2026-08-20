"""Domains of the derived-data engine (spec: docs/derived-data-spec.md).

A dirty cell is (patient_id, domain, date). Producers mark cells; the
refresh_patient drain recomputes derived artifacts from them. Report domains
migrate into the drain slice by slice — until a domain is registered here,
its reports keep regenerating via the legacy upload-path triggers and the
drain only refreshes cross-domain read-models (panel; summary later).
"""

from __future__ import annotations

from enum import Enum


class DataDomain(str, Enum):
    CGM = "cgm"
    MEAL = "meal"
    SLEEP = "sleep"
    FITNESS = "fitness"
    SMBG = "smbg"
    VITALS = "vitals"
    WORKOUT = "workout"


# Coalescing hint: how long the drain waits after a mark so a burst
# (multi-meal logging session, device sync, CGM stream tick) collapses into
# one run. Never a correctness dependency — the drain claims whatever is
# dirty when it fires.
_DEFAULT_DEFER_S = 60
DOMAIN_DEFER_S: dict[DataDomain, int] = {
    DataDomain.FITNESS: 120,
    DataDomain.SLEEP: 120,
    # LLU polls every 5 minutes; 15 min bounds regen frequency for streamers.
    DataDomain.CGM: 900,
}


def defer_for(domain: DataDomain) -> int:
    return DOMAIN_DEFER_S.get(domain, _DEFAULT_DEFER_S)
