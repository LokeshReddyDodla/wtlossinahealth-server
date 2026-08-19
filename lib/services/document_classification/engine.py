"""Deterministic document classification — no LLM, no I/O.

Stage 1 decides the document type (lab_report / radiology / other /
unclassified) from structural and vocabulary evidence in the extracted
text. Stage 2 assigns multi-label lab panels via anchor-analyte
scoring. `classify_document` is the only entry point.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from lib.services.document_classification.catalog import (
    COMPARATOR_RE,
    DATE_RE,
    EXTRA_ANALYTE_PATTERNS,
    LAB_HEADER_PATTERNS,
    NUM_RE,
    OTHER_DOC_PATTERNS,
    PANEL_RULES,
    RADIOLOGY_PATTERNS,
    RANGE_RE,
    UNIT_HINT_RE,
    UPTO_RE,
    PanelRule,
)
from lib.services.document_classification.models import (
    PANEL_ORDER,
    ClassificationEvidence,
    ClassificationResult,
    DocTypeEvidence,
    PanelEvidence,
)

# Bump on ANY rule/catalog/threshold change; the sweep reruns docs with
# classification.engine_version < ENGINE_VERSION. Must stay an int —
# Mongo compares strings lexicographically, which would break `$lt`.
ENGINE_VERSION: int = 1

MAX_TEXT_CHARS = 60_000
MIN_TEXT_CHARS = 30

# Stage-1 decision thresholds (summed evidence weights).
LAB_MIN_SCORE = 4.0
RADIOLOGY_MIN_SCORE = 2.0
OTHER_MIN_SCORE = 2.0
NOISE_FLOOR = 1.5
# Winner must beat the lab/radiology rival by this factor, else the
# document is left unclassified rather than guessed.
MARGIN = 1.25

_FILENAME_RADIOLOGY_RE = re.compile(
    r"x-?ray|scan|mri|\bct\b|usg|ultrasound", re.IGNORECASE
)
# InBody device exports embed "InBody" in the filename; their OCR is
# often too garbled for text evidence alone.
_FILENAME_OTHER_RE = re.compile(r"inbody", re.IGNORECASE)
_FILENAME_LAB_RE = re.compile(
    r"lab|report|cbc|blood|lft|kft|lipid|thyroid|urine", re.IGNORECASE
)


@dataclass
class _PanelMatch:
    rule: PanelRule
    score: float
    anchors: list[str]
    section_header: Optional[str]
    fired: bool


def classify_document(
    text_raw: Optional[str],
    file_name: Optional[str] = None,
    mime_type: Optional[str] = None,
    category: Optional[str] = None,
) -> ClassificationResult:
    """Classify one document from its already-extracted text.

    `category` is the client-supplied upload label ("report"/"other");
    it is accepted for API symmetry but never trusted as evidence.
    """
    now = datetime.now(timezone.utc)
    text = (text_raw or "").strip()

    if len(text) < MIN_TEXT_CHARS:
        return ClassificationResult(
            doc_type="unclassified",
            confidence=0.0,
            evidence=ClassificationEvidence(
                doc_type=DocTypeEvidence(reason="empty_text")
            ),
            engine_version=ENGINE_VERSION,
            classified_at=now,
        )

    text = text[:MAX_TEXT_CHARS]

    panel_matches = _match_panels(text)
    fired = [m for m in panel_matches if m.fired]

    doc_type, confidence, dt_evidence = _detect_doc_type(
        text, file_name, mime_type, fired
    )

    panels: list[str] = []
    panel_evidence: dict[str, PanelEvidence] = {}
    family = None
    if doc_type == "lab_report":
        for match in fired:
            panels.append(match.rule.panel)
            panel_evidence[match.rule.panel] = PanelEvidence(
                anchors=match.anchors,
                section_header=match.section_header,
            )
        if not panels:
            panels = ["other_lab"]
            panel_evidence["other_lab"] = PanelEvidence()
        panels.sort(key=PANEL_ORDER.index)
        family = _derive_family(fired)

    return ClassificationResult(
        doc_type=doc_type,  # type: ignore[arg-type]
        family=family,  # type: ignore[arg-type]
        panels=panels,  # type: ignore[arg-type]
        confidence=confidence,
        evidence=ClassificationEvidence(
            doc_type=dt_evidence, panels=panel_evidence
        ),
        engine_version=ENGINE_VERSION,
        classified_at=now,
    )


# ---------------------------------------------------------------------------
# Stage 2 — panels


def _match_panels(text: str) -> list[_PanelMatch]:
    matches = []
    for rule in PANEL_RULES:
        anchors: list[str] = []
        score = 0.0
        for anchor in (*rule.anchors, *rule.weak):
            if anchor.pattern.search(text):
                anchors.append(anchor.key)
                score += anchor.weight
        header = None
        for header_re in rule.section_headers:
            m = header_re.search(text)
            if m:
                header = m.group(0)
                break
        fired = score >= rule.min_score or (
            header is not None and score >= rule.min_score_with_header
        )
        matches.append(
            _PanelMatch(
                rule=rule,
                score=score,
                anchors=anchors,
                section_header=header,
                fired=fired,
            )
        )
    return matches


def _derive_family(fired: list[_PanelMatch]) -> Optional[str]:
    families = {m.rule.family for m in fired}
    if not families:
        return None
    if len(families) == 1:
        return families.pop()
    return "mixed"


# ---------------------------------------------------------------------------
# Stage 1 — document type


def _detect_doc_type(
    text: str,
    file_name: Optional[str],
    mime_type: Optional[str],
    fired: list[_PanelMatch],
) -> tuple[str, float, DocTypeEvidence]:
    result_lines = _count_result_lines(text)
    analyte_hits = _count_distinct_analytes(text)
    unit_hits = len(set(UNIT_HINT_RE.findall(text)))

    lab_headers = [
        v.key for v in LAB_HEADER_PATTERNS if v.pattern.search(text)
    ]
    lab_header_score = sum(
        v.weight for v in LAB_HEADER_PATTERNS if v.pattern.search(text)
    )
    radiology_hits = [
        v.key for v in RADIOLOGY_PATTERNS if v.pattern.search(text)
    ]
    radiology_score = sum(
        v.weight for v in RADIOLOGY_PATTERNS if v.pattern.search(text)
    )
    other_hits = [v.key for v in OTHER_DOC_PATTERNS if v.pattern.search(text)]
    other_score = sum(
        v.weight for v in OTHER_DOC_PATTERNS if v.pattern.search(text)
    )

    # A fired panel (numeric or narrative) is decisive lab evidence:
    # histopath/culture reports carry "Impression:"-style prose that
    # would otherwise lean radiology.
    lab_score = (
        min(result_lines, 10) * 1.0
        + min(analyte_hits, 10) * 0.75
        + lab_header_score
        + min(unit_hits, 8) * 0.5
        + len(fired) * 2.0
    )

    file_signals: list[str] = []
    if file_name and _FILENAME_RADIOLOGY_RE.search(file_name):
        radiology_score += 1.0
        file_signals.append("filename_radiology")
    elif file_name and _FILENAME_OTHER_RE.search(file_name):
        other_score += 2.0
        file_signals.append("filename_inbody")
    elif file_name and _FILENAME_LAB_RE.search(file_name):
        lab_score += 0.5
        file_signals.append("filename_lab")
    # An actual x-ray/scan image OCRs to almost nothing; a photo of a
    # lab report OCRs to a page of numbers.
    if (mime_type or "").startswith("image/") and len(text) < 200:
        radiology_score += 2.0
        file_signals.append("image_short_text")

    evidence = DocTypeEvidence(
        result_lines=result_lines,
        analyte_hits=analyte_hits,
        lab_headers=lab_headers,
        radiology_hits=radiology_hits,
        other_hits=other_hits,
        file_signals=file_signals,
    )

    scores = {
        "lab_report": lab_score,
        "radiology": radiology_score,
        "other": other_score,
    }
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (top_type, top), (_, second) = ranked[0], ranked[1]

    if top < NOISE_FLOOR:
        evidence.reason = "insufficient_signals"
        return "unclassified", 0.0, evidence

    confidence = round(min(0.99, top / (top + second + 1e-9)), 3)

    if top_type == "lab_report":
        if (
            lab_score >= LAB_MIN_SCORE
            and lab_score >= MARGIN * radiology_score
        ):
            return "lab_report", confidence, evidence
    elif top_type == "radiology":
        if (
            radiology_score >= RADIOLOGY_MIN_SCORE
            and radiology_score >= MARGIN * lab_score
        ):
            return "radiology", confidence, evidence
    else:
        if other_score >= OTHER_MIN_SCORE:
            return "other", confidence, evidence

    evidence.reason = "weak_or_ambiguous_signals"
    return "unclassified", 0.0, evidence


def _count_result_lines(text: str) -> int:
    count = 0
    for line in text.splitlines():
        numbers = len(NUM_RE.findall(line))
        # A dd-mm-yyyy date contributes 3 numeric tokens and a fake
        # dash-range; discount them so date rows don't count.
        numbers -= 3 * len(DATE_RE.findall(line))
        if (
            RANGE_RE.search(line)
            and numbers >= 3
            or COMPARATOR_RE.search(line)
            and numbers >= 2
            or UPTO_RE.search(line)
            and numbers >= 2
        ):
            count += 1
    return count


def _count_distinct_analytes(text: str) -> int:
    seen = set()
    for rule in PANEL_RULES:
        for anchor in (*rule.anchors, *rule.weak):
            if anchor.key not in seen and anchor.pattern.search(text):
                seen.add(anchor.key)
    for extra in EXTRA_ANALYTE_PATTERNS:
        if extra.key not in seen and extra.pattern.search(text):
            seen.add(extra.key)
    return len(seen)
