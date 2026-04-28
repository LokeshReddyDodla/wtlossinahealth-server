"""Rule-based finding interlinking.

Group findings across documents into LinkGroups so the timeline view can
show how the same lab / medication / diagnosis recurs over time.

Grouping key:
  * (code_system, code) when both are non-null (LOINC for labs,
    RxNorm for meds, ICD-10 / SNOMED for diagnoses).
  * fall back to ("name", name_normalized) otherwise.

LinkGroup id is a deterministic UUIDv5 so the same key always maps to
the same id across rebuilds — clients can stably color-code groups.
"""

from __future__ import annotations

import re
import uuid
from typing import Iterable, List, Tuple

from lib.schemas.profile_agent_documents import (
    Finding,
    LinkGroup,
    LinkOccurrence,
)

_NAMESPACE = uuid.UUID("00000000-0000-0000-0000-000000000042")


def normalize_name(name: str) -> str:
    """Lowercase, strip, collapse whitespace, drop punctuation."""
    if not name:
        return ""
    cleaned = re.sub(r"[^a-z0-9\s]", " ", name.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _group_key(f: Finding) -> Tuple[str, str]:
    if f.code_system and f.code:
        return (f.code_system, f.code.strip().lower())
    return ("name", f.name_normalized or normalize_name(f.name))


def _link_group_id(key: Tuple[str, str]) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{key[0]}::{key[1]}"))


def group_findings(
    findings_by_doc: Iterable[Tuple[str, Finding, dict]],
) -> List[LinkGroup]:
    """Return LinkGroups for an iterable of (document_id, finding, doc_metadata).

    `doc_metadata` is expected to carry at least `document_date`. `observed_at`
    on the finding is preferred over the document_date for the occurrence
    timestamp; document_date is the fallback.
    """
    groups: dict[Tuple[str, str], LinkGroup] = {}

    for document_id, finding, doc_meta in findings_by_doc:
        if not finding or not finding.name:
            continue
        key = _group_key(finding)
        if key not in groups:
            groups[key] = LinkGroup(
                link_group_id=_link_group_id(key),
                code_system=finding.code_system,
                code=finding.code,
                name=finding.name,
                finding_type=finding.finding_type,
                occurrences=[],
            )
        groups[key].occurrences.append(
            LinkOccurrence(
                document_id=document_id,
                document_date=doc_meta.get("document_date") if doc_meta else None,
                observed_at=finding.observed_at,
                value_numeric=finding.value_numeric,
                value_text=finding.value_text,
                unit=finding.unit,
            )
        )

    for group in groups.values():
        group.occurrences.sort(
            key=lambda o: (
                o.observed_at or o.document_date or _MIN_DT,
            )
        )

    return sorted(
        groups.values(),
        key=lambda g: (g.finding_type, g.name.lower()),
    )


from datetime import datetime as _dt

_MIN_DT = _dt.min
