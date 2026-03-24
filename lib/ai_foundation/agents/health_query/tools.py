"""
Health Tools — 4 tools the reasoning LLM can call to explore patient data.

Designed to match how a doctor THINKS, not our database schema:
  look_up          → "Show me specific health data"
  investigate_day  → "What happened on this day?"
  compare_baseline → "Is this normal for this patient?"
  find_patterns    → "Has this happened before?"

Profile + memory facts are PRE-LOADED in context, not tools.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from lib.ai_foundation.config import settings
from lib.ai_foundation.retrieval.base import RetrievalRequest, RetrievalResult

if TYPE_CHECKING:
    from lib.ai_foundation.retrieval.qdrant import QdrantRetriever

logger = logging.getLogger(__name__)

_MAX_TOOL_RESULT_CHARS = 2000


# ── Tool Definitions (OpenAI function calling format) ─────────────────────

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "look_up",
            "description": (
                "Look up specific health data for the patient. Returns individual records with full details. "
                "Use this for: meals (with nutrition breakdown), glucose/CGM readings (with values and ranges), "
                "fitness activity (steps, duration, calories), vitals (weight, BP, heart rate), "
                "SMBG readings, documents, hypo/hyper events, spike events."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "data_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Types of data to fetch. Options: meal, cgm_range_stats, cgm_summary_stats, "
                            "fitness_overview, vital, smbg, profile, patient_document, "
                            "hypo_event, hypo_stats, hyper_event, hyper_stats, "
                            "rapid_spike_event, rapid_spike_stats, rapid_drop_event, rapid_drop_stats"
                        ),
                    },
                    "date_start": {"type": "string", "description": "Start date (ISO format). e.g. '2026-03-18'"},
                    "date_end": {"type": "string", "description": "End date (ISO format). e.g. '2026-03-25'"},
                    "limit": {"type": "integer", "description": "Max records to return. Default 15."},
                },
                "required": ["data_types"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "investigate_day",
            "description": (
                "Get a chronological timeline of ALL health events on a specific day — "
                "meals, glucose readings, activity, vitals — sorted by time. "
                "Best for understanding cause-and-effect sequences. "
                "Use this when you see something interesting (spike, hypo, etc.) on a specific day "
                "and want to understand the full picture of what happened before and after."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "The specific day to investigate. e.g. '2026-03-18'"},
                    "hour_start": {"type": "integer", "description": "Start hour (0-23). Default 0."},
                    "hour_end": {"type": "integer", "description": "End hour (0-23). Default 24."},
                },
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_baseline",
            "description": (
                "Get statistical summary for a data type over a period. "
                "Returns: count, average values, min/max, and day-by-day entries. "
                "Use this to establish what is NORMAL for this patient so you can compare "
                "current readings against their own history — not population averages."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "data_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Data types to get baseline for.",
                    },
                    "days": {"type": "integer", "description": "How many days back to look. Default 30."},
                },
                "required": ["data_types"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_patterns",
            "description": (
                "Search for similar events or patterns in the patient's history using natural language. "
                "Uses semantic search across all health data. "
                "Use this to find: recurring meal patterns, glucose response to specific foods, "
                "exercise impact on glucose, historical trends, similar episodes, "
                "correlations between different health domains."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Natural language description of what to search for. "
                            "e.g. 'high carb meals that caused glucose spikes above 200' "
                            "or 'days with good glucose control' "
                            "or 'exercise sessions followed by improved glucose'"
                        ),
                    },
                    "days_back": {"type": "integer", "description": "How far back to search. Default 30."},
                    "limit": {"type": "integer", "description": "Max results. Default 10."},
                },
                "required": ["query"],
            },
        },
    },
]


# ── Tool Executor ─────────────────────────────────────────────────────────


class ToolExecutor:
    """Executes tool calls against Qdrant and formats results as readable text."""

    def __init__(self, qdrant: QdrantRetriever | None = None) -> None:
        self._qdrant = qdrant

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        patient_ids: list[str],
    ) -> str:
        """Execute a tool and return formatted text result."""
        if not self._qdrant:
            return "No data source available."

        try:
            if tool_name == "look_up":
                return await self._look_up(arguments, patient_ids)
            elif tool_name == "investigate_day":
                return await self._investigate_day(arguments, patient_ids)
            elif tool_name == "compare_baseline":
                return await self._compare_baseline(arguments, patient_ids)
            elif tool_name == "find_patterns":
                return await self._find_patterns(arguments, patient_ids)
            else:
                return f"Unknown tool: {tool_name}"
        except Exception as exc:
            logger.warning("Tool %s failed: %s", tool_name, exc)
            return f"Tool error: {exc}"

    async def execute_parallel(
        self,
        calls: list[tuple[str, dict[str, Any]]],
        patient_ids: list[str],
    ) -> list[str]:
        """Execute multiple tool calls concurrently.

        Args:
            calls: List of (tool_name, arguments) tuples.
            patient_ids: Patient IDs to query against.

        Returns:
            List of result strings in the same order as input calls.
        """
        tasks = [self.execute(name, args, patient_ids) for name, args in calls]
        return list(await asyncio.gather(*tasks))

    def get_openai_schemas(self) -> list[dict[str, Any]]:
        """Return tool definitions in OpenAI function calling format."""
        return TOOL_SCHEMAS

    # ── Tool implementations ──────────────────────────────────────────────

    async def _look_up(self, args: dict, patient_ids: list[str]) -> str:
        """Fetch specific health data records."""
        data_types = args.get("data_types", [])
        date_start = args.get("date_start")
        date_end = args.get("date_end")
        limit = args.get("limit", 15)

        results = await self._qdrant.retrieve_filtered(RetrievalRequest(
            query="",
            patient_ids=patient_ids,
            data_types=data_types,
            date_start=date_start,
            date_end=date_end,
            limit=limit,
        ))

        if not results:
            return f"No {', '.join(data_types)} data found for the specified period."

        return self._format_results(results)

    async def _investigate_day(self, args: dict, patient_ids: list[str]) -> str:
        """Get chronological timeline for a specific day."""
        date = args.get("date", "")
        hour_start = args.get("hour_start", 0)
        hour_end = args.get("hour_end", 24)

        # Fetch ALL data types for this day
        results = await self._qdrant.retrieve_filtered(RetrievalRequest(
            query="",
            patient_ids=patient_ids,
            data_types=[],  # all types
            date_start=date,
            date_end=date + "T23:59:59",
            limit=50,
            filters={"hour_start": hour_start, "hour_end": hour_end} if hour_start > 0 or hour_end < 24 else {},
        ))

        if not results:
            return f"No health data found for {date}."

        # Sort by time fields for chronological view
        sorted_items = sorted(
            results,
            key=lambda r: r.payload.get("start_time") or r.payload.get("time") or r.payload.get("date") or "",
        )

        lines = [f"Timeline for {date}:"]
        for r in sorted_items:
            p = r.payload
            dt = r.data_type or p.get("data_type", "unknown")
            time_val = p.get("time") or ""

            # Build readable line
            clean = {k: v for k, v in p.items()
                     if k not in ("data_type", "source", "patient_id", "embedding", "start_time", "end_time") and v is not None}

            parts = []
            for k, v in clean.items():
                if isinstance(v, dict):
                    inner = ", ".join(f"{ik}: {iv}" for ik, iv in v.items() if iv is not None)
                    if inner:
                        parts.append(f"{k}: ({inner})")
                else:
                    parts.append(f"{k}: {v}")

            time_prefix = f"  {time_val}" if time_val else "  "
            lines.append(f"{time_prefix} [{dt}] {', '.join(parts)}")

        return self._cap_result("\n".join(lines))

    async def _compare_baseline(self, args: dict, patient_ids: list[str]) -> str:
        """Get statistical baseline for comparison."""
        data_types = args.get("data_types", [])
        days = args.get("days", 30)

        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=days)).isoformat()

        results = await self._qdrant.retrieve_filtered(RetrievalRequest(
            query="",
            patient_ids=patient_ids,
            data_types=data_types,
            date_start=start,
            date_end=now.isoformat(),
            limit=50,
        ))

        if not results:
            return f"No {', '.join(data_types)} data found in the last {days} days."

        # Format as baseline summary + individual entries
        lines = [f"Baseline ({days} days, {len(results)} entries):"]

        # Show individual records (the LLM can compute averages)
        for r in results[:20]:
            p = r.payload
            clean = {k: v for k, v in p.items()
                     if k not in ("data_type", "source", "patient_id", "embedding", "start_time", "end_time") and v is not None}
            parts = [f"{k}: {v}" for k, v in clean.items() if not isinstance(v, (dict, list))]
            lines.append(f"  - {', '.join(parts)}")

        if len(results) > 20:
            lines.append(f"  ... and {len(results) - 20} more entries")

        return self._cap_result("\n".join(lines))

    async def _find_patterns(self, args: dict, patient_ids: list[str]) -> str:
        """Semantic search for patterns in patient history."""
        query = args.get("query", "")
        days_back = args.get("days_back", 30)
        limit = args.get("limit", 10)

        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=days_back)).isoformat()

        results = await self._qdrant.retrieve(RetrievalRequest(
            query=query,
            patient_ids=patient_ids,
            date_start=start,
            date_end=now.isoformat(),
            limit=limit,
        ))

        if not results:
            return f"No matching patterns found for: '{query}'"

        lines = [f"Pattern search: '{query}' ({len(results)} matches):"]
        for r in results:
            p = r.payload
            dt = r.data_type or p.get("data_type", "unknown")
            score = f" (relevance: {r.score:.2f})" if r.score else ""
            clean = {k: v for k, v in p.items()
                     if k not in ("data_type", "source", "patient_id", "embedding", "start_time", "end_time") and v is not None}
            parts = [f"{k}: {v}" for k, v in clean.items() if not isinstance(v, (dict, list))]
            lines.append(f"  - [{dt}]{score} {', '.join(parts)}")

        return self._cap_result("\n".join(lines))

    # ── Formatting helpers ────────────────────────────────────────────────

    @staticmethod
    def _format_results(results: list[RetrievalResult]) -> str:
        """Format results as readable text grouped by data type."""
        by_type: dict[str, list[dict]] = {}
        for r in results:
            dt = r.data_type or r.payload.get("data_type", "unknown")
            by_type.setdefault(dt, []).append(r.payload)

        sections: list[str] = []
        for dt, items in by_type.items():
            label = dt.replace("_", " ").upper()
            lines: list[str] = [f"{label} ({len(items)} entries):"]
            for item in items[:settings.MAX_RECORDS_PER_TYPE]:
                clean = {k: v for k, v in item.items()
                         if k not in ("data_type", "source", "patient_id", "embedding") and v is not None}
                parts: list[str] = []
                for k, v in clean.items():
                    if isinstance(v, dict):
                        inner = ", ".join(f"{ik}: {iv}" for ik, iv in v.items() if iv is not None)
                        if inner:
                            parts.append(f"{k}: ({inner})")
                    elif isinstance(v, list) and v and isinstance(v[0], dict):
                        parts.append(f"{k}: {len(v)} items")
                    else:
                        parts.append(f"{k}: {v}")
                lines.append("  - " + ", ".join(parts))

            if len(items) > settings.MAX_RECORDS_PER_TYPE:
                lines.append(f"  ... and {len(items) - settings.MAX_RECORDS_PER_TYPE} more")

            sections.append("\n".join(lines))

        return "\n\n".join(sections)

    @staticmethod
    def _cap_result(text: str) -> str:
        """Cap tool result to prevent context bloat."""
        if len(text) > _MAX_TOOL_RESULT_CHARS:
            return text[:_MAX_TOOL_RESULT_CHARS] + "\n... (truncated — ask for a narrower query)"
        return text
