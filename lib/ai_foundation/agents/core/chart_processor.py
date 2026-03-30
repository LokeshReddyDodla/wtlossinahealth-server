"""
Chart Processor — finds JSON chart blocks in LLM response text and
converts them to valid mermaid using the chart builder.

The LLM outputs ```chart-data JSON blocks. This module replaces them
with ```mermaid blocks that the frontend renders natively.
"""

from __future__ import annotations

import json
import logging
import re

from .chart_builder import build_mermaid

logger = logging.getLogger(__name__)

_CHART_BLOCK_RE = re.compile(
    r"```chart-data\s*\n(.*?)```",
    re.DOTALL,
)


def process_charts(text: str) -> str:
    """Replace all ```chart-data JSON blocks with ```mermaid blocks.

    If a chart block has invalid JSON or an unsupported type, it is
    removed entirely (the response still has tables with the same data).
    """
    if "```chart-data" not in text:
        return text

    def _replace(match: re.Match) -> str:
        raw = match.group(1).strip()
        try:
            chart = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Invalid chart JSON, removing block")
            return ""

        mermaid = build_mermaid(chart)
        if mermaid is None:
            logger.warning("Chart build returned None for type=%s, removing block", chart.get("type"))
            return ""

        return f"```mermaid\n{mermaid}\n```"

    return _CHART_BLOCK_RE.sub(_replace, text)
