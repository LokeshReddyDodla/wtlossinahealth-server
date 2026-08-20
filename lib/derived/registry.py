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
    # smbg/vitals are kick-only: no report domain (compute-on-read by
    # decision), their cells exist to run the finalizers (panel).
    SMBG = "smbg"
    VITALS = "vitals"


# User-action uploads drain immediately (the burst arrives inside one
# request; single-flight + durable cells coalesce the rest). Only the
# background LLU stream defers, to bound regen frequency for streamers —
# on a separate job id so it can never delay an immediate kick.
_DEFAULT_DEFER_S = 0
DOMAIN_DEFER_S: dict[DataDomain, int] = {
    DataDomain.CGM: 900,
}


def defer_for(domain: DataDomain) -> int:
    return DOMAIN_DEFER_S.get(domain, _DEFAULT_DEFER_S)


def get_report_domains() -> dict[DataDomain, object]:
    """Domains the drain computes. A domain absent here still gets its cells
    marked — its reports just keep regenerating via legacy triggers until it
    migrates in."""
    from lib.derived.domains.cgm import CGMReportDomain
    from lib.derived.domains.fitness import FitnessReportDomain
    from lib.derived.domains.meal import MealReportDomain
    from lib.derived.domains.sleep import SleepReportDomain

    return {
        DataDomain.MEAL: MealReportDomain(),
        DataDomain.CGM: CGMReportDomain(),
        DataDomain.SLEEP: SleepReportDomain(),
        DataDomain.FITNESS: FitnessReportDomain(),
    }
