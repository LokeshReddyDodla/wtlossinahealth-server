"""
Chart Builder — deterministic JSON→mermaid converter.

The LLM outputs chart data as JSON (what it's good at).
This module converts it to valid mermaid syntax (impossible to produce
invalid output because it constructs syntax from data, not by fixing text).

Supports 4 chart types: bar, line, pie, gantt.
"""

from __future__ import annotations

import json
import logging
import math
import re

logger = logging.getLogger(__name__)

# Strip characters that break mermaid titles/labels
_UNSAFE_CHARS = re.compile(r"[()–—%®©™°\"\n]")


def _clean(text: str) -> str:
    """Remove characters that break mermaid rendering."""
    return _UNSAFE_CHARS.sub("", text).strip()


def _auto_max(values: list[float | int]) -> int:
    """Pick a clean y-axis max above the highest value."""
    if not values:
        return 100
    peak = max(values)
    if peak <= 0:
        return 100
    magnitude = 10 ** math.floor(math.log10(max(peak, 1)))
    return int(math.ceil(peak / magnitude) * magnitude)


def build_mermaid(chart: dict) -> str | None:
    """Convert a chart JSON dict to a valid mermaid string.

    Returns None if the chart is invalid or has an unknown type.
    """
    chart_type = chart.get("type", "")

    try:
        if chart_type in ("bar", "line"):
            return _build_xy(chart)
        if chart_type == "pie":
            return _build_pie(chart)
        if chart_type == "gantt":
            return _build_gantt(chart)
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Chart build failed for type=%s: %s", chart_type, exc)
        return None

    logger.warning("Unknown chart type: %s", chart_type)
    return None


def _build_xy(chart: dict) -> str | None:
    """Build an xychart-beta (bar/line) diagram."""
    title = _clean(chart.get("title", ""))
    x_labels = chart.get("x", [])
    y_label = _clean(chart.get("y_label", "Value"))
    series_list = chart.get("series", [])

    if not x_labels or not series_list:
        return None

    # Collect all values to compute y-axis range
    all_values: list[float] = []
    for s in series_list:
        all_values.extend(v for v in s.get("data", []) if isinstance(v, (int, float)))

    y_max = _auto_max(all_values)
    x_formatted = ", ".join(f'"{_clean(str(l))}"' for l in x_labels[:10])

    lines = [
        "xychart-beta",
        f'    title "{title}"' if title else "",
        f'    x-axis [{x_formatted}]',
        f'    y-axis "{y_label}" 0 --> {y_max}',
    ]

    for s in series_list:
        s_type = s.get("type", chart["type"])  # inherit from chart if not specified
        data = s.get("data", [])[:10]
        data_str = ", ".join(str(v) for v in data)
        keyword = "line" if s_type == "line" else "bar"
        lines.append(f"    {keyword} [{data_str}]")

    return "\n".join(line for line in lines if line)


def _build_pie(chart: dict) -> str | None:
    """Build a pie diagram."""
    title = _clean(chart.get("title", ""))
    segments = chart.get("segments", [])

    if not segments:
        return None

    lines = [f"pie title {title}" if title else "pie"]
    for seg in segments:
        label = _clean(str(seg.get("label", "")))
        value = seg.get("value", 0)
        lines.append(f'    "{label}" : {value}')

    return "\n".join(lines)


def _build_gantt(chart: dict) -> str | None:
    """Build a gantt timeline diagram."""
    title = _clean(chart.get("title", ""))
    sections = chart.get("sections", [])

    if not sections:
        return None

    lines = [
        "gantt",
        f"    title {title}" if title else "",
        "    dateFormat HH:mm",
        "    axisFormat %H:%M",
    ]

    for section in sections:
        name = _clean(str(section.get("name", "")))
        lines.append(f"    section {name}")
        for event in section.get("events", []):
            label = _clean(str(event.get("label", "")))
            start = event.get("start", "00:00")
            end = event.get("end", "00:00")
            style = event.get("style", "")
            style_prefix = f"{style}, " if style else ""
            lines.append(f"        {label}    :{style_prefix}{start}, {end}")

    return "\n".join(line for line in lines if line)
