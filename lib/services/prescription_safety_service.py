"""Prescription safety co-signer.

Runs before a prescription is issued: deterministic allergy and duplicate
name-matches (authoritative, never model-dependent) plus one LLM pass for
drug–drug interactions, therapeutic-class duplicates, and allergy
cross-reactivity. No drug database exists in the platform, so the interaction
judgment is model-based; a deterministic allergy hit always stands.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from lib.ai_foundation.models.gateway import ModelGateway
from lib.ai_foundation.models.registry import ModelTask
from lib.core.postgres_store import PostgresStore
from lib.models.patient import Patient
from lib.models.patient_medication import PatientMedication
from lib.schemas.prescription_safety import (
    AllergyConflict,
    DuplicateTherapy,
    PrescriptionSafetyResult,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a clinical medication-safety checker assisting a prescriber. You are given
a set of NEW medicines being prescribed, the patient's CURRENT active medicines,
their drug ALLERGIES, and their CONDITIONS. Identify only real, clinically
meaningful safety issues:

- interactions: drug–drug interactions between any of the new medicines, or
  between a new medicine and a current one. Give the drug pair, a severity
  (low/moderate/high), and a one-sentence explanation.
- duplicates: a new medicine that duplicates the therapeutic class of a current
  medicine (e.g. two ACE inhibitors), even when the names differ.
- allergy_conflicts: a new medicine the patient is likely allergic to, including
  cross-reactivity within a drug class (e.g. a cephalosporin with a penicillin
  allergy). Severity is high.

Rules:
- Report ONLY genuine concerns. If there are none, return empty lists.
- Do NOT invent interactions to seem thorough. Conservative and correct.
- Use the exact medicine names as given.
"""


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


class PrescriptionSafetyService:
    def __init__(self, gateway: ModelGateway, postgres_store: PostgresStore):
        self.gateway = gateway
        self.postgres_store = postgres_store

    async def check(
        self, patient_id: str, medicines: list, is_current_regimen: bool = False
    ) -> PrescriptionSafetyResult:
        """medicines: objects/dicts with at least `name` (ConfirmedMedicine works).

        is_current_regimen: the medicines ARE the patient's active list (a
        self-audit), so the exact-name "already active" check is skipped —
        every med would otherwise match itself.
        """
        new_names = [_med_name(m) for m in medicines if _med_name(m)]

        allergies, conditions, pregnant, active = await self._load_context(patient_id)

        # ── deterministic, authoritative ──────────────────────────────────
        allergy_conflicts: list[AllergyConflict] = []
        for name in new_names:
            for a in allergies:
                if _norm(a["name"]) and _norm(a["name"]) in _norm(name):
                    allergy_conflicts.append(
                        AllergyConflict(drug=name, allergy=a["name"], reaction=a["reaction"], severity="high")
                    )
        duplicates: list[DuplicateTherapy] = []
        if not is_current_regimen:
            active_names = {_norm(m) for m in active}
            for name in new_names:
                if _norm(name) in active_names:
                    duplicates.append(
                        DuplicateTherapy(new_drug=name, existing_drug=name, reason="Already on the active list")
                    )

        # ── LLM: interactions + class duplicates + cross-reactivity ───────
        llm = await self._llm_check(patient_id, new_names, active, [a["name"] for a in allergies], conditions, pregnant)

        # merge, de-duping deterministic vs model on (drug, allergy)/(name) keys
        seen_allergy = {(_norm(c.drug), _norm(c.allergy)) for c in allergy_conflicts}
        for c in llm.allergy_conflicts:
            if (_norm(c.drug), _norm(c.allergy)) not in seen_allergy:
                allergy_conflicts.append(c)
        seen_dupe = {_norm(d.new_drug) for d in duplicates}
        for d in llm.duplicates:
            if _norm(d.new_drug) not in seen_dupe:
                duplicates.append(d)

        return PrescriptionSafetyResult(
            interactions=llm.interactions,
            duplicates=duplicates,
            allergy_conflicts=allergy_conflicts,
        )

    async def _load_context(self, patient_id: str):
        async with self.postgres_store.get_session() as s:
            patient = (
                await s.execute(
                    select(Patient)
                    .options(
                        selectinload(Patient.drug_allergies),
                        selectinload(Patient.medical_histories),
                        selectinload(Patient.diabetic_history),
                    )
                    .where(Patient.patient_id == patient_id)
                )
            ).scalar_one_or_none()
            active = (
                await s.execute(
                    select(PatientMedication.name).where(
                        PatientMedication.patient_id == patient_id,
                        PatientMedication.status.in_(["active", "as_needed"]),
                    )
                )
            ).scalars().all()

        if patient is None:
            return [], [], False, list(active)

        allergies = [
            {"name": a.allergy_name or a.name, "reaction": getattr(a, "reaction", None)}
            for a in (patient.drug_allergies or [])
            if (a.allergy_name or a.name)
        ]
        conditions = [h.condition for h in (patient.medical_histories or []) if h.condition]
        dh = patient.diabetic_history
        dh = dh[0] if isinstance(dh, list) and dh else dh
        pregnant = bool(getattr(dh, "is_pregnant", False)) if dh else False
        return allergies, conditions, pregnant, list(active)

    async def _llm_check(
        self, patient_id, new_names, active, allergies, conditions, pregnant
    ) -> PrescriptionSafetyResult:
        if not new_names:
            return PrescriptionSafetyResult()
        payload = {
            "new_medicines": new_names,
            "current_medicines": active,
            "allergies": allergies,
            "conditions": conditions,
            "pregnant": pregnant,
        }
        trace_id = str(uuid4())
        try:
            result, meta = await self.gateway.extract(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": f"Check this prescription context:\n{payload}"},
                ],
                response_model=PrescriptionSafetyResult,
                task=ModelTask.STRUCTURED_ANALYSIS,
                model_id="claude-sonnet-4-6",
                trace_id=trace_id,
            )
            logger.info(
                "Rx safety check: %d interactions, %d dupes, %d allergy (%dms)",
                len(result.interactions), len(result.duplicates), len(result.allergy_conflicts),
                meta.latency_ms,
            )
            return result
        except Exception:
            # Never block issuing on an LLM failure — the deterministic allergy /
            # duplicate checks still stand in check().
            logger.exception("Rx safety LLM check failed for %s", patient_id)
            return PrescriptionSafetyResult()


def _med_name(m) -> str:
    if isinstance(m, dict):
        return m.get("name") or ""
    return getattr(m, "name", "") or ""
