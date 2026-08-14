from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

DocTypeLiteral = Literal["lab_report", "radiology", "other", "unclassified"]

# Order doubles as the canonical display/sort order for panels.
PanelLiteral = Literal[
    "cbc",
    "metabolic_bmp_cmp",
    "lft",
    "kft",
    "lipid",
    "hba1c_glucose",
    "thyroid",
    "coagulation",
    "cardiac",
    "immunology_serology",
    "urinalysis",
    "micro_culture_sensitivity",
    "surgical_pathology",
    "cytopathology",
    "molecular_pcr",
    "other_lab",
]

PANEL_ORDER: tuple[str, ...] = PanelLiteral.__args__  # type: ignore[attr-defined]

FamilyLiteral = Literal[
    "quantitative", "semi_quantitative", "narrative", "mixed"
]


class DocTypeEvidence(BaseModel):
    result_lines: int = 0
    analyte_hits: int = 0
    lab_headers: list[str] = Field(default_factory=list)
    radiology_hits: list[str] = Field(default_factory=list)
    other_hits: list[str] = Field(default_factory=list)
    file_signals: list[str] = Field(default_factory=list)
    reason: Optional[str] = None


class PanelEvidence(BaseModel):
    anchors: list[str] = Field(default_factory=list)
    section_header: Optional[str] = None


class ClassificationEvidence(BaseModel):
    doc_type: DocTypeEvidence = Field(default_factory=DocTypeEvidence)
    panels: dict[str, PanelEvidence] = Field(default_factory=dict)


class ClassificationResult(BaseModel):
    doc_type: DocTypeLiteral
    family: Optional[FamilyLiteral] = None
    panels: list[PanelLiteral] = Field(default_factory=list)
    confidence: float = 0.0
    evidence: ClassificationEvidence = Field(
        default_factory=ClassificationEvidence
    )
    engine_version: int
    classified_at: datetime

    def to_mongo(self) -> dict:
        return self.model_dump()
