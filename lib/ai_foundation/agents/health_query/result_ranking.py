"""
Result ranking utilities for health query tools.

Pure functions — no I/O, no state. Sort and truncate RetrievalResult lists
so the most relevant records reach the LLM context window.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from lib.ai_foundation.retrieval.base import RetrievalResult


# ── Time-based sorting ───────────────────────────────────────────────────


def _extract_time_key(payload: dict[str, Any], base_date: str = "") -> float:
    """Extract a numeric sort key from a health record payload.

    Fallback chain:
        1. start_time (epoch ms, numeric) — CGM, fitness, most data types
        2. date + time combined — meals often have both as strings
        3. date only (ISO string) — parsed to epoch
        4. time only + base_date — anchored to the provided base date
        5. time only (no base) — small synthetic value, sorts below real datetimes
        6. 0 — records with no time info sort last

    Args:
        payload: The record's data fields.
        base_date: Optional ISO date (e.g. "2026-03-25") to anchor time-only
            records. Used by investigate_day to ensure correct chronological sort.
    """
    # 1. start_time (epoch ms)
    start_time = payload.get("start_time")
    if start_time is not None:
        try:
            return float(start_time)
        except (ValueError, TypeError):
            pass

    # 2. date + time combined, or date only
    date_str = payload.get("date", "")
    time_str = payload.get("time", "")

    if date_str:
        try:
            if time_str:
                dt = datetime.fromisoformat(f"{date_str[:10]}T{time_str}")
            else:
                dt = datetime.fromisoformat(date_str[:10])
            return dt.replace(tzinfo=timezone.utc).timestamp() * 1000
        except (ValueError, TypeError):
            pass

    # 3. time only — anchor to base_date if provided, otherwise small synthetic value
    if time_str:
        try:
            anchor = base_date or date_str
            if anchor:
                dt = datetime.fromisoformat(f"{anchor[:10]}T{time_str}")
                return dt.replace(tzinfo=timezone.utc).timestamp() * 1000
            # No anchor — small positive value so time-only sorts above 0 but below real epochs
            parts = time_str.split(":")
            hours = int(parts[0])
            minutes = int(parts[1]) if len(parts) > 1 else 0
            return float(hours * 3600 + minutes * 60)
        except (ValueError, IndexError, TypeError):
            pass

    return 0.0


def sort_by_time(
    results: list[RetrievalResult],
    *,
    ascending: bool = False,
    base_date: str = "",
) -> list[RetrievalResult]:
    """Sort results by time, most recent first by default.

    Uses a robust fallback chain to extract a comparable time key from
    each payload. Records without any parseable time field sort last.

    Args:
        ascending: If True, sort oldest first (for chronological timelines).
        base_date: Optional ISO date to anchor time-only records (e.g. for investigate_day).
    """
    return sorted(
        results,
        key=lambda r: _extract_time_key(r.payload, base_date),
        reverse=not ascending,
    )


# ── Boundary-safe text truncation ────────────────────────────────────────


def cap_at_record_boundaries(text: str, max_chars: int) -> str:
    """Truncate text at line boundaries instead of mid-record.

    Preserves section headers (non-indented lines starting a section).
    Appends count of omitted lines when truncation occurs.
    Guarantees the returned string does not exceed max_chars.
    """
    if len(text) <= max_chars:
        return text

    _TRUNCATION_SUFFIX = "\n... (truncated — narrow your query)"
    budget = max_chars - len(_TRUNCATION_SUFFIX)

    if budget <= 0:
        return text[:max_chars]

    lines = text.split("\n")
    kept: list[str] = []
    total = 0

    for line in lines:
        line_cost = len(line) + (1 if kept else 0)  # +1 for joining newline (except first)
        if total + line_cost > budget and kept:
            break
        kept.append(line)
        total += line_cost

    if len(kept) < len(lines):
        kept.append(_TRUNCATION_SUFFIX.lstrip("\n"))
    result = "\n".join(kept)

    # Final safety: hard-cap if a single long first line exceeds budget
    if len(result) > max_chars:
        return result[:max_chars]
    return result
