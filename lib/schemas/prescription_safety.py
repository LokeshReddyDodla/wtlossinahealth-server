"""Typed result for the prescription safety co-signer.

Deterministic pre-checks (allergy name-match, duplicate name/dose) plus an LLM
pass for drug–drug interactions, therapeutic-class duplicates, and allergy
cross-reactivity. There is no drug database in the platform, so the interaction
judgment is model-based; the allergy string-match is always authoritative.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from lib.schemas.medication import ExtractedMedicine

Severity = Literal["low", "moderate", "high"]


class PrescriptionSafetyRequest(BaseModel):
    """Medicines to check — only `name` is required (ExtractedMedicine)."""

    medicines: list[ExtractedMedicine] = Field(default_factory=list)
    # True when the medicines ARE the patient's active regimen (self-audit),
    # which suppresses the exact-name "already active" duplicate check.
    is_current_regimen: bool = False


class DrugInteraction(BaseModel):
    drugs: list[str]
    severity: Severity
    explanation: str


class DuplicateTherapy(BaseModel):
    new_drug: str
    existing_drug: str
    reason: str


class AllergyConflict(BaseModel):
    drug: str
    allergy: str
    reaction: str | None = None
    severity: Severity = "high"


class PrescriptionSafetyResult(BaseModel):
    interactions: list[DrugInteraction] = Field(default_factory=list)
    duplicates: list[DuplicateTherapy] = Field(default_factory=list)
    allergy_conflicts: list[AllergyConflict] = Field(default_factory=list)

    @property
    def has_blocking(self) -> bool:
        """Allergy conflicts are the hard-stop the CP must see before issuing."""
        return bool(self.allergy_conflicts)
