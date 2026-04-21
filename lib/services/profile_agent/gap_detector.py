"""Pure gap detection and mode selection.

Given (patient ORM, draft_changes, config) produce:
  * agent mode for this turn
  * ordered list of missing required fields (gate-aware)
  * per-section completion map
  * overall completion percentage

All inputs are read-only. No I/O.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from lib.schemas.profile_agent import AgentMode, GapFieldInfo, GapReport
from lib.services.profile_agent.config import SECTIONS, EntityConfig, FieldConfig
from lib.services.profile_agent.gate_eval import (
    field_value_from_patient,
    gate_satisfied,
)


class MergedView:
    """Overlay of (patient ORM state ∪ draft_changes).

    Draft values take precedence. Used by gate_eval so gates re-evaluate
    against pending user answers mid-conversation (e.g. user flipped
    smoke_status from false→true in the draft → smoking follow-up
    questions immediately appear as required).
    """

    def __init__(self, patient, draft_changes: Dict[str, Any]) -> None:
        self._patient = patient
        self._draft = draft_changes

    def get(self, field_key: str, entity: EntityConfig) -> Any:
        if field_key in self._draft:
            return self._draft[field_key]
        return field_value_from_patient(field_key, entity, self._patient)


def compute_gap_report(
    patient,
    draft_changes: Dict[str, Any] | None = None,
) -> GapReport:
    draft_changes = draft_changes or {}
    view = MergedView(patient, draft_changes)

    sections_complete: Dict[str, bool] = {}
    missing: List[GapFieldInfo] = []
    required_total = 0
    required_present = 0

    for section in SECTIONS:
        section_complete = True
        for entity in section["entities"]:
            for field in entity["fields"]:
                if not field.get("required"):
                    continue
                if not gate_satisfied(field, entity, view):
                    continue
                required_total += 1
                value = view.get(field["key"], entity)
                if _is_empty(value):
                    section_complete = False
                    missing.append(
                        GapFieldInfo(
                            field=field["key"],
                            label=field["label"],
                            section=section["key"],
                            entity=entity["key"],
                            type=field["type"],
                            required=True,
                        )
                    )
                else:
                    required_present += 1
        sections_complete[section["key"]] = section_complete

    pct = required_present / required_total if required_total else 1.0
    mode = _detect_mode(required_present, pct)

    return GapReport(
        mode=mode.value,
        completion_pct=round(pct, 3),
        sections=sections_complete,
        missing_fields=missing,
    )


def next_missing_field(report: GapReport) -> GapFieldInfo | None:
    """First missing field in deterministic section/field order."""
    return report.missing_fields[0] if report.missing_fields else None


def _detect_mode(present: int, pct: float) -> AgentMode:
    if present == 0:
        return AgentMode.ONBOARDING_FRESH
    if pct < 0.5:
        return AgentMode.ONBOARDING_RESUMING
    if pct < 1.0:
        return AgentMode.HYBRID
    return AgentMode.UPDATE


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False
