"""Recompute the Patient.profile_completion JSONB from current values.

The old agents flip `is_complete` per section when they apply changes —
but that drifts from reality. We recompute from the authoritative source
(the ORM state post-apply) so completion always reflects truth.

A section is complete when every `required` field in it (with a satisfied
gate) has a non-empty value on the patient.
"""

from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.orm.attributes import flag_modified

from lib.services.profile_agent.config import SECTIONS
from lib.services.profile_agent.gate_eval import field_value_from_patient, gate_satisfied


def recompute_profile_completion(patient) -> None:
    """Mutates patient.profile_completion in place."""
    pc: Dict[str, Any] = patient.profile_completion or {}

    for section in SECTIONS:
        skey = section["key"]
        is_complete = _section_complete(section, patient)
        if skey not in pc:
            pc[skey] = {"is_complete": is_complete, "is_mandatory": True}
        else:
            pc[skey]["is_complete"] = is_complete
            pc[skey].setdefault("is_mandatory", True)

    patient.profile_completion = pc
    flag_modified(patient, "profile_completion")


def _section_complete(section, patient) -> bool:
    for entity in section["entities"]:
        for field in entity["fields"]:
            if not field.get("required"):
                continue
            if not gate_satisfied(field, entity, patient_view=_PatientView(patient)):
                continue
            value = field_value_from_patient(field["key"], entity, patient)
            if _is_empty(value):
                return False
    return True


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, (str,)) and value.strip() == "":
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


class _PatientView:
    """Adapter so gate_eval.gate_satisfied can read from an ORM patient
    the same way it reads from a (profile ∪ draft) dict at gap-detection time."""

    def __init__(self, patient) -> None:
        self._patient = patient

    def get(self, field_key: str, entity) -> Any:
        return field_value_from_patient(field_key, entity, self._patient)
