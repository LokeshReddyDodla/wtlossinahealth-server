"""
Evidence & Citation Layer — deterministic investigation summary builder.

Builds a structured evidence trail from tool execution results, formatted
per audience role. The evidence ledger is built incrementally as tools
execute (pruning-safe), never from final messages which may be pruned.

No LLM calls. Pure parsing and formatting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lib.ai_foundation.agents.health_query.specialists import SpecialistFindings
    from lib.ai_foundation.models.gateway import LLMToolResponse

from lib.ai_foundation.agents.health_query.tools import NO_DATA_PREFIX

# ── Regex patterns for parsing record counts from tool result text ────────

# "MEAL (5 entries):" — standard _format_results pattern
_RE_ENTRIES = re.compile(r"\((\d+) entries\)")
# "Baseline (30 days, 12 entries):" — compare_baseline pattern
_RE_DAYS_ENTRIES = re.compile(r"\((\d+) days?, (\d+) entries\)")
# "Pattern search: '...' (7 matches):" — find_patterns pattern
_RE_MATCHES = re.compile(r"\((\d+) matches\)")
# "Timeline for 2026-03-25:" — investigate_day pattern (count lines starting with [ )
_RE_TIMELINE_ITEM = re.compile(r"^\s+.*\[.+\]", re.MULTILINE)

# ── Reverse mapping: data_type → human-readable domain name ──────────────

# Built lazily from contracts to avoid circular imports at module level
_DATA_TYPE_TO_DOMAIN: dict[str, str] | None = None


def _get_type_to_domain() -> dict[str, str]:
    global _DATA_TYPE_TO_DOMAIN
    if _DATA_TYPE_TO_DOMAIN is None:
        from lib.ai_foundation.agents.health_query.contracts import DOMAIN_MAPPING
        _DATA_TYPE_TO_DOMAIN = {}
        for domain, types in DOMAIN_MAPPING.items():
            for dt in types:
                _DATA_TYPE_TO_DOMAIN[dt.value] = domain.value
    return _DATA_TYPE_TO_DOMAIN


# ── Models ────────────────────────────────────────────────────────────────


@dataclass
class EvidenceItem:
    """One tool call's contribution to the evidence trail."""

    tool: str                       # "look_up", "investigate_day", etc.
    data_types: list[str]           # ["meal", "cgm_range_stats"]
    date_range: str                 # "Mar 25–27" or "last 30 days" or ""
    record_count: int | None        # parsed from result text, None if unparseable
    had_data: bool                  # False if result was [NO_DATA]


@dataclass
class InvestigationSummary:
    """Aggregated evidence from an entire investigation."""

    items: list[EvidenceItem] = field(default_factory=list)
    domains_with_data: list[str] = field(default_factory=list)
    domains_without_data: list[str] = field(default_factory=list)
    date_coverage: str = ""
    total_records: int | None = None


# ── Extraction — from tool round (incremental, pruning-safe) ─────────────


def extract_evidence_from_tool_round(
    response: LLMToolResponse,
    tool_messages: list[dict[str, Any]],
) -> list[EvidenceItem]:
    """Extract EvidenceItems from a completed tool round.

    Called immediately after tool execution, before any pruning can occur.
    Uses the LLM response (for tool call args) and tool messages (for results).
    """
    items: list[EvidenceItem] = []
    tc_by_id = {tc.id: tc for tc in response.tool_calls}

    for msg in tool_messages:
        tc_id = msg.get("tool_call_id", "")
        tc = tc_by_id.get(tc_id)
        if not tc:
            continue

        content = msg.get("content", "")
        args = tc.arguments
        tool_name = tc.function_name

        # Parse record count + NO_DATA detection
        had_data = not content.startswith(NO_DATA_PREFIX)

        # Extract data_types from args (investigate_day/find_patterns don't have them)
        data_types = args.get("data_types", [])
        if isinstance(data_types, str):
            data_types = [data_types]
        if not data_types and had_data and tool_name in ("investigate_day", "find_patterns"):
            data_types = _parse_data_types_from_result(content)

        # Extract date range
        date_range = _extract_date_range(tool_name, args)
        record_count = _parse_record_count(content) if had_data else 0

        items.append(EvidenceItem(
            tool=tool_name,
            data_types=data_types,
            date_range=date_range,
            record_count=record_count,
            had_data=had_data,
        ))

    return items


def extract_evidence_from_fallback(
    tool_name: str,
    args: dict[str, Any],
    result_text: str,
) -> EvidenceItem:
    """Extract evidence from a single fallback tool call (not via tool_round)."""
    data_types = args.get("data_types", [])
    if isinstance(data_types, str):
        data_types = [data_types]

    had_data = not result_text.startswith(NO_DATA_PREFIX)
    record_count = _parse_record_count(result_text) if had_data else 0

    return EvidenceItem(
        tool=tool_name,
        data_types=data_types,
        date_range=_extract_date_range(tool_name, args),
        record_count=record_count,
        had_data=had_data,
    )


# ── Summary building ─────────────────────────────────────────────────────


def build_summary(evidence_ledger: list[EvidenceItem]) -> InvestigationSummary:
    """Build an aggregated summary from the evidence ledger.

    Deduplicates items with the same (tool, data_types, date_range).
    """
    if not evidence_ledger:
        return InvestigationSummary()

    # Deduplicate: merge items with same (tool, frozenset(data_types), date_range)
    merged: dict[tuple[str, frozenset[str], str], EvidenceItem] = {}
    for item in evidence_ledger:
        key = (item.tool, frozenset(item.data_types), item.date_range)
        if key in merged:
            existing = merged[key]
            # Merge: keep had_data=True if either had data, sum record counts
            existing.had_data = existing.had_data or item.had_data
            if existing.record_count is not None and item.record_count is not None:
                existing.record_count += item.record_count
            elif item.record_count is not None:
                existing.record_count = item.record_count
        else:
            merged[key] = EvidenceItem(
                tool=item.tool,
                data_types=list(item.data_types),
                date_range=item.date_range,
                record_count=item.record_count,
                had_data=item.had_data,
            )

    items = list(merged.values())

    # Compute domain coverage
    type_to_domain = _get_type_to_domain()
    domains_seen: set[str] = set()
    domains_with_data: set[str] = set()

    for item in items:
        for dt in item.data_types:
            domain = type_to_domain.get(dt, dt)
            domains_seen.add(domain)
            if item.had_data:
                domains_with_data.add(domain)

    domains_without = domains_seen - domains_with_data

    # Date coverage
    all_ranges = [item.date_range for item in items if item.date_range]
    date_coverage = ", ".join(sorted(set(all_ranges))) if all_ranges else ""

    # Total records
    counts = [item.record_count for item in items if item.record_count is not None and item.had_data]
    total_records = sum(counts) if counts else None

    return InvestigationSummary(
        items=items,
        domains_with_data=sorted(domains_with_data),
        domains_without_data=sorted(domains_without),
        date_coverage=date_coverage,
        total_records=total_records,
    )


def build_summary_from_findings(findings: list[SpecialistFindings]) -> InvestigationSummary:
    """Build evidence summary from coordinator specialist findings."""
    items: list[EvidenceItem] = []

    for f in findings:
        total_count = 0
        has_parsed_records = False

        for result_text in f.data_gathered:
            if result_text.startswith(NO_DATA_PREFIX):
                continue
            count = _parse_record_count(result_text)
            if count is not None:
                total_count += count
                has_parsed_records = True
            # Entries without parseable counts (e.g. LLM analysis text) are ignored

        # Map specialist domain key to canonical domain for label lookup
        canonical = _SPECIALIST_TO_DOMAIN.get(f.domain, f.domain)
        items.append(EvidenceItem(
            tool="specialist",
            data_types=[canonical],
            date_range="",  # specialists don't expose date args easily
            record_count=total_count if has_parsed_records else None,
            had_data=has_parsed_records,
        ))

    return build_summary(items)


# ── Formatters — role-aware ──────────────────────────────────────────────


def format_patient(summary: InvestigationSummary) -> str:
    """Natural language evidence for patients. 1-2 sentences."""
    if not summary.items:
        return ""

    # All NO_DATA
    if not any(item.had_data for item in summary.items):
        return "No health data was found for the requested period."

    # Build natural description of what was found
    parts: list[str] = []
    for item in summary.items:
        if not item.had_data:
            continue
        desc = _describe_data_types_patient(item.data_types)
        if not desc:
            desc = "health data"
        count_str = f"{item.record_count} " if item.record_count else ""
        range_str = f" from {item.date_range}" if item.date_range else ""
        parts.append(f"{count_str}{desc}{range_str}")

    result = "Based on " + _join_natural(parts) + "."

    # Mention gaps
    if summary.domains_without_data:
        gap_labels = [_DOMAIN_PATIENT_LABELS.get(d, f"{d} data") for d in summary.domains_without_data]
        result += f" No {_join_natural(gap_labels)} was available for this period."

    return result


def format_provider(summary: InvestigationSummary) -> str:
    """Structured evidence block for care providers / admins."""
    if not summary.items:
        return ""

    # All NO_DATA
    if not any(item.had_data for item in summary.items):
        return "No health data was found for the requested period."

    # Data sources
    source_parts: list[str] = []
    for item in summary.items:
        if not item.had_data:
            continue
        label = _describe_data_types_provider(item.data_types)
        if not label:
            label = "health records"
        count_str = f"{item.record_count} " if item.record_count else ""
        range_str = f" ({item.date_range})" if item.date_range else ""
        source_parts.append(f"{count_str}{label}{range_str}")

    result = "**Sources:** " + ", ".join(source_parts)

    # Gaps
    if summary.domains_without_data:
        gap_labels = [f"no {_DOMAIN_PROVIDER_LABELS.get(d, d)}" for d in summary.domains_without_data]
        result += f" | Gaps: {', '.join(gap_labels)}"

    return result


# ── Confidence & Coverage ─────────────────────────────────────────────────


def compute_coverage_confidence(summary: InvestigationSummary, *, skip_date_penalty: bool = False) -> float:
    """Compute a deterministic data-coverage confidence score (0.1–1.0).

    Measures how complete the supporting data is, not truthfulness or quality.
    No LLM call — pure math from the investigation summary.

    Args:
        skip_date_penalty: If True, don't penalize for missing date_coverage.
            Used by coordinator path where specialists don't expose date args.
    """
    if not summary.items:
        return 0.1

    # All NO_DATA
    if not any(item.had_data for item in summary.items):
        return 0.1

    score = 1.0

    # Penalty for missing domains: -0.15 each
    score -= len(summary.domains_without_data) * 0.15

    # Penalty for thin coverage: fewer than 3 total records
    if summary.total_records is not None and summary.total_records < 3:
        score -= 0.2

    # Penalty for no date range context (skip for coordinator/specialist path)
    if not skip_date_penalty and not summary.date_coverage:
        score -= 0.1

    return max(round(score, 2), 0.1)


def format_coverage_note(summary: InvestigationSummary) -> str:
    """Return a coverage note when data is thin or incomplete. Empty if coverage is good."""
    if not summary.items:
        return ""

    parts: list[str] = []

    # Thin record count
    if summary.total_records is not None and summary.total_records < 5:
        if not any(item.had_data for item in summary.items):
            parts.append("No health data was found for the requested period.")
        else:
            parts.append(f"Limited data: only {summary.total_records} record{'s' if summary.total_records != 1 else ''} found.")

    # Missing domains
    if summary.domains_without_data:
        gap_labels = [_DOMAIN_PATIENT_LABELS.get(d, f"{d} data") for d in summary.domains_without_data]
        parts.append(f"Partial coverage: no {_join_natural(gap_labels)} available.")

    return " ".join(parts)


def format_data_gaps(summary: InvestigationSummary) -> list[str] | None:
    """Return human-readable list of missing domains, or None if no gaps."""
    if not summary.domains_without_data:
        return None
    return [_DOMAIN_PATIENT_LABELS.get(d, f"{d} data") for d in summary.domains_without_data]


# ── Conflict Detection ───────────────────────────────────────────────────


def detect_conflicts(evidence_ledger: list[EvidenceItem]) -> list[str]:
    """Detect contradictions in the evidence trail. Deterministic, no LLM.

    Checks:
    1. Data-exists contradiction: one tool found NO_DATA for a type, another found data.
    2. Count discrepancy: same domain queried by different tools with >3x record count difference.

    Returns human-readable conflict notes, or empty list.
    """
    if len(evidence_ledger) < 2:
        return []

    type_to_domain = _get_type_to_domain()
    conflicts: list[str] = []

    # Group items by domain (dedup: same item only counted once per domain)
    domain_items: dict[str, list[EvidenceItem]] = {}
    for item in evidence_ledger:
        seen_domains: set[str] = set()
        for dt in item.data_types:
            domain = type_to_domain.get(dt, dt)
            if domain not in seen_domains:
                seen_domains.add(domain)
                domain_items.setdefault(domain, []).append(item)

    for domain, items in domain_items.items():
        has_data_items = [i for i in items if i.had_data]
        no_data_items = [i for i in items if not i.had_data]
        label = _DOMAIN_PATIENT_LABELS.get(domain, f"{domain} data")

        # Type 1: data-exists contradiction
        if has_data_items and no_data_items:
            conflicts.append(
                f"Conflicting availability for {label}: one query found data "
                f"but another returned no results. The data may depend on the "
                f"date range or filters used."
            )

        # Type 2: count discrepancy (>3x difference between tools with data)
        counts = [i.record_count for i in has_data_items if i.record_count and i.record_count > 0]
        if len(counts) >= 2:
            min_c, max_c = min(counts), max(counts)
            if min_c > 0 and max_c / min_c > 3:
                conflicts.append(
                    f"Record count discrepancy for {label}: queries returned "
                    f"{min_c} and {max_c} records. Different date ranges or "
                    f"filters may explain the difference."
                )

    return conflicts


# ── Internal helpers ─────────────────────────────────────────────────────


def _parse_data_types_from_result(text: str) -> list[str]:
    """Extract data types from investigate_day/find_patterns result text.

    investigate_day has lines like: "  08:00 [meal] ..."
    _format_results has headers like: "MEAL (5 entries):"
    Validates against known data types to avoid false matches from log tags.
    """
    type_to_domain = _get_type_to_domain()
    valid_types = set(type_to_domain.keys())

    # Try timeline format: [data_type] tags
    types_from_tags = set(re.findall(r"\[(\w+)\]", text))
    # Filter to known data types only (excludes [NO_DATA], [info], etc.)
    valid_tags = sorted(t for t in types_from_tags if t in valid_types)
    if valid_tags:
        return valid_tags
    # Try section headers: "DATA_TYPE (N entries):"
    types_from_headers = set(re.findall(r"^(\w[\w ]+)\s+\(\d+ entries\)", text, re.MULTILINE))
    if types_from_headers:
        normalized = [h.lower().replace(" ", "_") for h in types_from_headers]
        return sorted(t for t in normalized if t in valid_types)
    return []


def _extract_date_range(tool_name: str, args: dict[str, Any]) -> str:
    """Extract a human-readable date range from tool arguments."""
    if tool_name == "investigate_day":
        return args.get("date", "")
    if tool_name == "compare_baseline":
        days = args.get("days", 30)
        return f"last {days} days"
    if tool_name == "find_patterns":
        days = args.get("days_back", 30)
        return f"last {days} days"
    # look_up
    date_start = args.get("date_start", "")
    date_end = args.get("date_end", "")
    if date_start and date_end:
        # Shorten: "2026-03-25" → "Mar 25"
        start_short = _short_date(date_start)
        end_short = _short_date(date_end)
        return f"{start_short}–{end_short}" if start_short != end_short else start_short
    if date_start:
        return f"from {_short_date(date_start)}"
    if date_end:
        return f"until {_short_date(date_end)}"
    return ""


def _short_date(iso_date: str) -> str:
    """Convert ISO date to short format: '2026-03-25' → 'Mar 25'."""
    try:
        parts = iso_date[:10].split("-")
        if len(parts) >= 3:
            months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            month_idx = int(parts[1]) - 1
            return f"{months[month_idx]} {int(parts[2])}"
    except (ValueError, IndexError):
        pass
    return iso_date[:10]


def _parse_record_count(text: str) -> int | None:
    """Parse record count from tool result text."""
    # Try "(X days, Y entries)" first (most specific)
    m = _RE_DAYS_ENTRIES.search(text[:200])
    if m:
        return int(m.group(2))

    # Try "(N matches)" — find_patterns header
    m = _RE_MATCHES.search(text[:200])
    if m:
        return int(m.group(1))

    # Try "(N entries)" — can appear multiple times across sections
    total = 0
    found = False
    for m in _RE_ENTRIES.finditer(text):
        total += int(m.group(1))
        found = True
    if found:
        return total

    # Try timeline items (investigate_day)
    timeline_matches = _RE_TIMELINE_ITEM.findall(text)
    if timeline_matches:
        return len(timeline_matches)

    return None


def _describe_data_types_patient(data_types: list[str]) -> str:
    """Convert data_type list to patient-friendly description."""
    type_to_domain = _get_type_to_domain()
    # Group by domain for natural language
    domains: list[str] = []
    seen: set[str] = set()
    for dt in data_types:
        domain = type_to_domain.get(dt, dt.replace("_", " "))
        if domain not in seen:
            seen.add(domain)
            domains.append(_DOMAIN_PATIENT_LABELS.get(domain, f"{domain} data"))
    return _join_natural(domains)


def _describe_data_types_provider(data_types: list[str]) -> str:
    """Convert data_type list to clinical description."""
    type_to_domain = _get_type_to_domain()
    domains: list[str] = []
    seen: set[str] = set()
    for dt in data_types:
        domain = type_to_domain.get(dt, dt.replace("_", " "))
        if domain not in seen:
            seen.add(domain)
            domains.append(_DOMAIN_PROVIDER_LABELS.get(domain, f"{domain} records"))
    return ", ".join(domains)


def _join_natural(items: list[str]) -> str:
    """Join items in natural language: 'a, b, and c'."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


# Specialist domain key → canonical domain (for label lookup)
_SPECIALIST_TO_DOMAIN: dict[str, str] = {
    "glucose": "cgm",
    "nutrition": "meal",
    "fitness": "fitness",
    "vitals": "vitals",
    "sleep": "sleep",
    "documents": "documents",
}

# Patient-friendly labels for domains
_DOMAIN_PATIENT_LABELS: dict[str, str] = {
    "cgm": "glucose readings",
    "meal": "meals",
    "fitness": "activity data",
    "smbg": "blood sugar checks",
    "sleep": "sleep data",
    "vitals": "vitals",
    "profile": "profile information",
    "documents": "medical documents",
}

# Provider labels for domains
_DOMAIN_PROVIDER_LABELS: dict[str, str] = {
    "cgm": "CGM readings",
    "meal": "meal records",
    "fitness": "fitness entries",
    "smbg": "SMBG readings",
    "sleep": "sleep records",
    "vitals": "vitals",
    "profile": "profile data",
    "documents": "documents",
}
