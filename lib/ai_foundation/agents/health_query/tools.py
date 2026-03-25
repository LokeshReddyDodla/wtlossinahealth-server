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
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from lib.ai_foundation.config import settings
from lib.ai_foundation.retrieval.base import RetrievalRequest, RetrievalResult

if TYPE_CHECKING:
    from lib.ai_foundation.models.gateway import LLMToolResponse, ToolCall
    from lib.ai_foundation.retrieval.qdrant import QdrantRetriever

logger = logging.getLogger(__name__)

# Structural sentinel — tool results starting with this prefix indicate empty results.
# Used by reasoning engine and specialists for early-exit decisions.
NO_DATA_PREFIX = "[NO_DATA] "

# Warning returned for duplicate tool calls.
DUP_WARNING = "You already fetched this exact data. Try a different tool or different parameters."


# ── Tool round helpers ────────────────────────────────────────────────────


def is_no_data(result: str) -> bool:
    """Check if a tool result indicates no data was found.

    Uses the structural NO_DATA_PREFIX sentinel set by ToolExecutor,
    not fragile string matching on natural language.
    """
    return result.startswith(NO_DATA_PREFIX)


def build_assistant_tool_call_msg(response: LLMToolResponse) -> dict[str, Any]:
    """Build an assistant message with tool_calls in OpenAI format."""
    return {
        "role": "assistant",
        "content": response.content or None,
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function_name,
                    "arguments": json.dumps(tc.arguments),
                },
            }
            for tc in response.tool_calls
        ],
    }


@dataclass
class ToolRoundResult:
    """Result of executing one round of tool calls."""

    tool_messages: list[dict[str, Any]] = dc_field(default_factory=list)
    assistant_message: dict[str, Any] = dc_field(default_factory=dict)
    executed_count: int = 0
    all_no_data: bool = False
    results: list[str] = dc_field(default_factory=list)

# Maps specialist domain → Qdrant data_type values the specialist should use
_DOMAIN_DATA_TYPES: dict[str, list[str]] = {
    "glucose": [
        "cgm_range_stats", "cgm_summary_stats", "smbg",
        "hypo_event", "hypo_stats", "hyper_event", "hyper_stats",
        "rapid_spike_event", "rapid_spike_stats", "rapid_drop_event", "rapid_drop_stats",
    ],
    "nutrition": ["meal"],
    "fitness": ["fitness_overview", "fitness_activity_distribution", "fitness_inactive_periods"],
    "vitals": ["vital"],
    "sleep": ["sleep"],
    "documents": ["patient_document"],
}


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
        patient_names: dict[str, str] | None = None,
    ) -> str:
        """Execute a tool and return formatted text result."""
        if not self._qdrant:
            return "No data source available."

        names = patient_names or {}
        try:
            if tool_name == "look_up":
                return await self._look_up(arguments, patient_ids, names)
            elif tool_name == "investigate_day":
                return await self._investigate_day(arguments, patient_ids, names)
            elif tool_name == "compare_baseline":
                return await self._compare_baseline(arguments, patient_ids, names)
            elif tool_name == "find_patterns":
                return await self._find_patterns(arguments, patient_ids, names)
            else:
                return f"Unknown tool: {tool_name}"
        except Exception as exc:
            logger.warning("Tool %s failed: %s", tool_name, exc)
            return f"Tool error: {exc}"

    async def execute_parallel(
        self,
        calls: list[tuple[str, dict[str, Any]]],
        patient_ids: list[str],
        patient_names: dict[str, str] | None = None,
    ) -> list[str]:
        """Execute multiple tool calls concurrently."""
        tasks = [self.execute(name, args, patient_ids, patient_names) for name, args in calls]
        return list(await asyncio.gather(*tasks))

    async def execute_tool_round(
        self,
        response: LLMToolResponse,
        patient_ids: list[str],
        seen_calls: set[str],
        patient_names: dict[str, str] | None = None,
    ) -> ToolRoundResult:
        """Execute one round of tool calls with dedup, returning a ToolRoundResult.

        Handles partitioning new vs duplicate calls, parallel execution,
        and building the assistant + tool messages for the conversation.
        """
        assistant_msg = build_assistant_tool_call_msg(response)

        # Partition tool calls: new vs duplicate
        to_execute: list[tuple[str, dict[str, Any], str]] = []  # (name, args, tc_id)
        duplicate_ids: list[str] = []
        for tc in response.tool_calls:
            call_key = f"{tc.function_name}:{json.dumps(tc.arguments, sort_keys=True)}"
            if call_key in seen_calls:
                duplicate_ids.append(tc.id)
            else:
                seen_calls.add(call_key)
                to_execute.append((tc.function_name, tc.arguments, tc.id))

        # Execute all non-duplicate calls in parallel
        if to_execute:
            results = await self.execute_parallel(
                [(name, args) for name, args, _ in to_execute],
                patient_ids,
                patient_names,
            )
        else:
            results = []

        # Build tool messages
        tool_messages: list[dict[str, Any]] = []
        for (name, args, tc_id), result_text in zip(to_execute, results):
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": result_text,
            })

        # Duplicate warnings
        for tc_id in duplicate_ids:
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": DUP_WARNING,
            })

        return ToolRoundResult(
            tool_messages=tool_messages,
            assistant_message=assistant_msg,
            executed_count=len(to_execute),
            all_no_data=bool(results) and all(is_no_data(r) for r in results),
            results=results,
        )

    def get_openai_schemas(self) -> list[dict[str, Any]]:
        """Return tool definitions in OpenAI function calling format."""
        return TOOL_SCHEMAS

    def get_schemas_for_domain(self, domain: str) -> list[dict[str, Any]]:
        """Return tool schemas filtered to a specific specialist domain.

        The look_up and compare_baseline tools get their data_types description
        narrowed to only the domain's types. investigate_day and find_patterns
        stay unfiltered (they're cross-domain by nature).
        """
        domain_types = _DOMAIN_DATA_TYPES.get(domain)
        if not domain_types:
            return TOOL_SCHEMAS

        import copy
        filtered: list[dict[str, Any]] = []
        for schema in TOOL_SCHEMAS:
            func_name = schema.get("function", {}).get("name", "")

            if func_name in ("look_up", "compare_baseline") and domain_types:
                # Deep copy and replace data_types description
                s = copy.deepcopy(schema)
                props = s["function"]["parameters"]["properties"]
                types_str = ", ".join(domain_types)
                if func_name == "look_up":
                    props["data_types"]["description"] = (
                        f"Types of data to fetch. For this domain use: {types_str}"
                    )
                elif func_name == "compare_baseline":
                    props["data_types"]["description"] = (
                        f"Data types to get baseline for. For this domain use: {types_str}"
                    )
                filtered.append(s)
            else:
                # investigate_day and find_patterns are shared across all domains
                filtered.append(schema)

        return filtered

    # ── Tool implementations ──────────────────────────────────────────────

    async def _look_up(self, args: dict, patient_ids: list[str], names: dict[str, str] | None = None) -> str:
        """Fetch specific health data records."""
        data_types = args.get("data_types", [])
        date_start = args.get("date_start")
        date_end = args.get("date_end")
        limit = args.get("limit", settings.LOOKUP_DEFAULT_LIMIT)

        logger.info(
            "look_up: types=%s dates=%s→%s pids=%s limit=%s",
            data_types, date_start, date_end, patient_ids[:1], limit,
        )

        results = await self._qdrant.retrieve_filtered(RetrievalRequest(
            query="",
            patient_ids=patient_ids,
            data_types=data_types,
            date_start=date_start,
            date_end=date_end,
            limit=limit,
        ))

        logger.info("look_up: %d results returned", len(results))

        if not results:
            return f"{NO_DATA_PREFIX}No {', '.join(data_types)} data found for the specified period."

        return self._format_results(results)

    async def _investigate_day(self, args: dict, patient_ids: list[str], names: dict[str, str] | None = None) -> str:
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
            limit=settings.QDRANT_RESULT_LIMIT,
            filters={"hour_start": hour_start, "hour_end": hour_end} if hour_start > 0 or hour_end < 24 else {},
        ))

        if not results:
            return f"{NO_DATA_PREFIX}No health data found for {date}."

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
            pid = p.get("patient_id", "")
            name = self._patient_names.get(pid)
            if name:
                clean["patient"] = name

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

    async def _compare_baseline(self, args: dict, patient_ids: list[str], names: dict[str, str] | None = None) -> str:
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
            limit=settings.QDRANT_RESULT_LIMIT,
        ))

        if not results:
            return f"{NO_DATA_PREFIX}No {', '.join(data_types)} data found in the last {days} days."

        # Format as baseline summary + individual entries
        lines = [f"Baseline ({days} days, {len(results)} entries):"]

        # Show individual records (the LLM can compute averages)
        for r in results[:20]:
            p = r.payload
            clean = {k: v for k, v in p.items()
                     if k not in ("data_type", "source", "patient_id", "embedding", "start_time", "end_time") and v is not None}
            pid = p.get("patient_id", "")
            name = self._patient_names.get(pid)
            if name:
                clean["patient"] = name
            parts = [f"{k}: {v}" for k, v in clean.items() if not isinstance(v, (dict, list))]
            lines.append(f"  - {', '.join(parts)}")

        if len(results) > 20:
            lines.append(f"  ... and {len(results) - 20} more entries")

        return self._cap_result("\n".join(lines))

    async def _find_patterns(self, args: dict, patient_ids: list[str], names: dict[str, str] | None = None) -> str:
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
            return f"{NO_DATA_PREFIX}No matching patterns found for: '{query}'"

        lines = [f"Pattern search: '{query}' ({len(results)} matches):"]
        for r in results:
            p = r.payload
            dt = r.data_type or p.get("data_type", "unknown")
            score = f" (relevance: {r.score:.2f})" if r.score else ""
            clean = {k: v for k, v in p.items()
                     if k not in ("data_type", "source", "patient_id", "embedding", "start_time", "end_time") and v is not None}
            pid = p.get("patient_id", "")
            name = self._patient_names.get(pid)
            if name:
                clean["patient"] = name
            parts = [f"{k}: {v}" for k, v in clean.items() if not isinstance(v, (dict, list))]
            lines.append(f"  - [{dt}]{score} {', '.join(parts)}")

        return self._cap_result("\n".join(lines))

    # ── Formatting helpers ────────────────────────────────────────────────

    def _format_results(self, results: list[RetrievalResult]) -> str:
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
                # Inject patient name so the LLM knows who this record belongs to
                pid = item.get("patient_id", "")
                name = (names or {}).get(pid)
                if name:
                    clean["patient"] = name
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
        max_chars = settings.REASONING_MAX_TOOL_RESULT_CHARS
        if len(text) > max_chars:
            return text[:max_chars] + "\n... (truncated — ask for a narrower query)"
        return text
