"""Gate-field auto-inference.

When a user answers a gated field (e.g. `cigarettes_per_day=10`) without
setting the gate (e.g. `smoke_status=true`), the LLM sometimes omits the
gate field. If we persist as-is, we can end up with inconsistent data
(a row claiming "non-smoker, 10 cigarettes/day"). This helper adds the
gate field to the draft with the value that makes the gate satisfy —
unless the user explicitly set the gate field this turn.
"""

from __future__ import annotations

from typing import Any, Dict

from lib.services.profile_agent.config import (
    FIELD_TO_CONFIG,
    FIELD_TO_ENTITY,
    entity_by_key,
)
from lib.services.profile_agent.gate_eval import _values_equal
from lib.services.profile_agent.gap_detector import MergedView


def infer_gate_fields(patient, draft_changes: Dict[str, Any]) -> Dict[str, Any]:
    """Mutates `draft_changes` in place; fills gate fields so data stays
    consistent with the gated field the user answered.

    Rules:
      * Skip if the user explicitly set the gate field in this draft.
      * Skip `not_equals` and multi-condition gates (ambiguous).
      * Otherwise, force the gate field to `cond['equals']` — even if the
        current patient value would contradict it. The rationale: the
        user just told us something that implies the gate value; the
        prior state is now stale.
    """
    for field_key in list(draft_changes.keys()):
        cfg = FIELD_TO_CONFIG.get(field_key)
        if not cfg:
            continue
        gate = cfg.get("gate")
        if not gate:
            continue

        for cond in gate:
            target_field = cond["field"]
            if target_field in draft_changes:
                continue  # user explicitly set the gate
            if "equals" not in cond or "not_equals" in cond:
                continue  # ambiguous — skip
            draft_changes[target_field] = cond["equals"]

    return draft_changes
