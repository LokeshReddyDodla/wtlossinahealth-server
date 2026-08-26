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
    from lib.ai_foundation.models.gateway import LLMToolResponse
    from lib.ai_foundation.retrieval.qdrant import QdrantRetriever
    from lib.ai_foundation.agents.proactive_monitor.insight_tracker import InsightTracker
    from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver
    from lib.ai_foundation.clinical.metabolic.service import MetabolicService

logger = logging.getLogger(__name__)

# Structural sentinel — tool results starting with this prefix indicate empty results.
# Used by reasoning engine and specialists for early-exit decisions.
NO_DATA_PREFIX = "[NO_DATA] "

# Keys excluded when formatting payloads for LLM consumption
_PAYLOAD_EXCLUDE = frozenset(
    {
        "data_type",
        "source",
        "patient_id",
        "embedding",
        "start_time",
        "end_time",
        # Raw epoch-ms internals — the LLM can only mangle these into wrong
        # dates; human-readable date/time fields are already in the payload.
        "vector_updated_at",
        "uploaded_at",
    }
)

_WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _format_payload(
    payload: dict,
    names: dict[str, str] | None = None,
    *,
    include_nested: bool = False,
    exclude_extra: frozenset[str] | None = None,
) -> str:
    """Format a payload dict as a readable 'key: value' string, injecting patient name."""
    exclude = _PAYLOAD_EXCLUDE | exclude_extra if exclude_extra else _PAYLOAD_EXCLUDE
    clean = {k: v for k, v in payload.items() if k not in exclude and v is not None}
    pid = payload.get("patient_id", "")
    name = (names or {}).get(pid)
    if name:
        clean["patient"] = name

    parts: list[str] = []
    for k, v in clean.items():
        if isinstance(v, dict):
            if include_nested:
                inner = ", ".join(f"{ik}: {iv}" for ik, iv in v.items() if iv is not None)
                if inner:
                    parts.append(f"{k}: ({inner})")
        elif isinstance(v, list):
            if include_nested and v and isinstance(v[0], dict):
                parts.append(f"{k}: {len(v)} items")
        elif k == "day_of_week" and isinstance(v, int) and 0 <= v <= 6:
            # Python weekday int (Mon=0) — models misread the convention
            # (e.g. assume Sun=0), so spell out the name.
            parts.append(f"{k}: {_WEEKDAY_NAMES[v]}")
        else:
            parts.append(f"{k}: {v}")
    return ", ".join(parts)

# Canonical data_type values derived from HealthDataType enum — used in tool schema enums.
# This ensures the LLM can ONLY pass valid values (OpenAI enforces enum constraints).
from lib.ai_foundation.agents.health_query.contracts import HealthDataType

# Valid data_type values — derived from enum, used for schema enum + validation.
_VALID_DATA_TYPES: list[str] = [dt.value for dt in HealthDataType]

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

# Derive domain → data_type mapping from specialist specs (single source of truth)
from lib.ai_foundation.agents.health_query.specialists import DEFAULT_SPECS as _DEFAULT_SPECS
_DOMAIN_DATA_TYPES: dict[str, list[str]] = {
    domain: spec.data_types for domain, spec in _DEFAULT_SPECS.items()
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
                "body_composition (any body-composition scan, any device — body fat %, skeletal muscle, visceral fat, segmental lean, phase angle), "
                "SMBG readings, documents, hypo/hyper events, spike events."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "data_types": {
                        "type": "array",
                        "items": {"type": "string", "enum": _VALID_DATA_TYPES},
                        "description": "Types of data to fetch. Use EXACT values from the enum.",
                    },
                    "date_start": {"type": "string", "description": "Start date (ISO format). e.g. '2026-03-18'"},
                    "date_end": {"type": "string", "description": "End date (ISO format). e.g. '2026-03-25'"},
                    "limit": {"type": "integer", "description": "Max records to return. Default 200."},
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
                        "items": {"type": "string", "enum": _VALID_DATA_TYPES},
                        "description": "Data types to get baseline for. Use EXACT values from the enum.",
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
    {
        "type": "function",
        "function": {
            "name": "get_recent_insights",
            "description": (
                "Fetch recent proactive health insights (notifications) sent to this patient. "
                "Use when the patient asks about their notifications, alerts, or what the system detected."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max insights to return. Default 5."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "metabolic_profile",
            "description": (
                "Get the patient's metabolic risk profile from the clinical engine. "
                "Returns: metabolic phenotype tier (insulin-sensitive/resistant/mixed), "
                "BMIQ body composition score, weight trend, CGM driver, and safety flags. "
                "Use when the patient asks about their metabolic health, diabetes risk, "
                "body composition, weight trajectory, or overall clinical picture."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]


# ── Tool Executor ─────────────────────────────────────────────────────────


class ToolExecutor:
    """Executes tool calls against Qdrant and formats results as readable text."""

    def __init__(
        self,
        qdrant: QdrantRetriever | None = None,
        insight_tracker: InsightTracker | None = None,
        patient_resolver: PatientNameResolver | None = None,
        metabolic_service: MetabolicService | None = None,
    ) -> None:
        self._qdrant = qdrant
        self._insight_tracker = insight_tracker
        self._patient_resolver = patient_resolver
        self._metabolic = metabolic_service

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        patient_ids: list[str],
        patient_names: dict[str, str] | None = None,
    ) -> str:
        """Execute a tool and return formatted text result."""
        if tool_name == "get_recent_insights":
            return await self._get_recent_insights(arguments, patient_ids)
        if tool_name == "metabolic_profile":
            return await self._metabolic_profile(patient_ids)

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
            logger.warning("Tool %s failed: %s", tool_name, exc, exc_info=True)
            return (
                f"SYSTEM ERROR: {tool_name} failed to retrieve data. "
                f"The data may exist but could not be loaded. "
                f"Do NOT conclude that data is missing based on this error."
            )

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

        Specialists stay inside their domain sandbox. Only domain-safe tools are
        exposed, and the data_types enum is narrowed to the domain's types.
        """
        domain_types = _DOMAIN_DATA_TYPES.get(domain)
        if not domain_types:
            return TOOL_SCHEMAS

        import copy
        filtered: list[dict[str, Any]] = []
        for schema in TOOL_SCHEMAS:
            func_name = schema.get("function", {}).get("name", "")

            if func_name in ("look_up", "compare_baseline") and domain_types:
                s = copy.deepcopy(schema)
                props = s["function"]["parameters"]["properties"]
                types_str = ", ".join(domain_types)
                props["data_types"]["items"]["enum"] = list(domain_types)
                if func_name == "look_up":
                    props["data_types"]["description"] = (
                        f"Types of data to fetch. For this domain use: {types_str}"
                    )
                else:
                    props["data_types"]["description"] = (
                        f"Data types to get baseline for. For this domain use: {types_str}"
                    )
                filtered.append(s)
            elif func_name in ("investigate_day", "find_patterns", "get_recent_insights"):
                # These tools are domain-agnostic — pass through without data_type filtering
                filtered.append(schema)

        return filtered

    # ── Panel scaling helpers ─────────────────────────────────────────────

    def _panel_char_limit(self, patient_ids: list[str]) -> int:
        """Scale tool result char limit by patient count."""
        n = max(1, len(patient_ids))
        if n <= 1:
            return settings.REASONING_MAX_TOOL_RESULT_CHARS
        return min(settings.REASONING_MAX_TOOL_RESULT_CHARS * n, settings.PANEL_MAX_TOOL_RESULT_CHARS)

    def _panel_lookup_limit(self, patient_ids: list[str], explicit_limit: int | None) -> int:
        """Return effective look_up record limit, scaled for panel queries."""
        if explicit_limit is not None:
            return explicit_limit
        n = max(1, len(patient_ids))
        if n <= 1:
            return settings.LOOKUP_DEFAULT_LIMIT
        return settings.PANEL_LOOKUP_LIMIT * n

    def _panel_records_per_type(self, patient_ids: list[str]) -> int:
        """Return per-type record cap, scaled for panel queries."""
        n = max(1, len(patient_ids))
        if n <= 1:
            return settings.MAX_RECORDS_PER_TYPE
        return min(settings.PANEL_RECORDS_PER_PATIENT * n, settings.PANEL_MAX_RECORDS_PER_TYPE)

    # ── Tool implementations ──────────────────────────────────────────────

    async def _look_up(self, args: dict, patient_ids: list[str], names: dict[str, str] | None = None) -> str:
        """Fetch specific health data records."""
        data_types = args.get("data_types", [])
        date_start = args.get("date_start")
        date_end = args.get("date_end")
        limit = self._panel_lookup_limit(patient_ids, args.get("limit"))

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

        # Filter to only results matching the requested data_types.
        # The Qdrant filter always includes profile as a should-branch,
        # which returns results even when the requested types have no data.
        # Use expanded types so paired types (e.g. sleep → sleep_checkin) aren't dropped.
        if data_types:
            from lib.ai_foundation.retrieval.qdrant import _expand_data_types
            requested = set(_expand_data_types(data_types))
            results = [r for r in results if (r.data_type or r.payload.get("data_type")) in requested]

        if not results:
            return f"{NO_DATA_PREFIX}No {', '.join(data_types)} data found for the specified period."

        from lib.ai_foundation.agents.health_query.result_ranking import sort_by_time
        results = sort_by_time(results)
        return self._format_results(
            results, names,
            requested_types=data_types,
            patient_ids=patient_ids,
        )

    async def _investigate_day(self, args: dict, patient_ids: list[str], names: dict[str, str] | None = None) -> str:
        """Get chronological timeline for a specific day."""
        date = args.get("date", "")
        if not date:
            return f"{NO_DATA_PREFIX}No date specified for investigate_day."
        try:
            hour_start = int(args.get("hour_start", 0))
            hour_end = int(args.get("hour_end", 24))
        except (ValueError, TypeError):
            hour_start, hour_end = 0, 24

        # Fetch a larger window for day timelines so busy days don't silently drop earlier events.
        timeline_limit = max(settings.QDRANT_RESULT_LIMIT, 200)
        results = await self._qdrant.retrieve_filtered(RetrievalRequest(
            query="",
            patient_ids=patient_ids,
            data_types=[],  # all types
            date_start=date,
            date_end=date + "T23:59:59",
            limit=timeline_limit,
            filters={"hour_start": hour_start, "hour_end": hour_end} if hour_start > 0 or hour_end < 24 else {},
        ))

        if not results:
            return f"{NO_DATA_PREFIX}No health data found for {date}."

        results = [r for r in results if (r.data_type or r.payload.get("data_type")) != "profile"]
        if not results:
            return f"{NO_DATA_PREFIX}No health data found for {date}."

        # Sort chronologically using robust numeric time key
        from lib.ai_foundation.agents.health_query.result_ranking import sort_by_time
        sorted_items = sort_by_time(results, ascending=True, base_date=date)

        lines = [f"Timeline for {date}:"]
        if len(sorted_items) >= timeline_limit:
            lines.append(f"Note: showing the most recent {timeline_limit} events for this day.")
        for r in sorted_items:
            p = r.payload
            dt = r.data_type or p.get("data_type", "unknown")
            time_val = p.get("time") or ""

            # Build readable line
            formatted = _format_payload(p, names, include_nested=True)
            time_prefix = f"  {time_val}" if time_val else "  "
            lines.append(f"{time_prefix} [{dt}] {formatted}")

        return self._cap_result("\n".join(lines), self._panel_char_limit(patient_ids))

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

        # Post-filter to requested types (Qdrant may include profile/other via should-branch)
        if data_types:
            from lib.ai_foundation.retrieval.qdrant import _expand_data_types
            requested = set(_expand_data_types(data_types))
            results = [r for r in results if (r.data_type or r.payload.get("data_type")) in requested]

        if not results:
            return f"{NO_DATA_PREFIX}No {', '.join(data_types)} data found in the last {days} days."

        from lib.ai_foundation.agents.health_query.result_ranking import sort_by_time
        results = sort_by_time(results)

        # Scale display limit for panel queries
        display_limit = self._panel_records_per_type(patient_ids)
        lines = [f"Baseline ({days} days, {len(results)} entries):"]

        # Show individual records (the LLM can compute averages)
        for r in results[:display_limit]:
            lines.append(f"  - {_format_payload(r.payload, names)}")

        if len(results) > display_limit:
            lines.append(f"  ... and {len(results) - display_limit} more entries")

        return self._cap_result("\n".join(lines), self._panel_char_limit(patient_ids))

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

        # Semantic retrieval may still surface profile rows via broad indexing.
        # Keep pattern search focused on event/data records.
        results = [r for r in results if (r.data_type or r.payload.get("data_type")) != "profile"]

        if not results:
            return f"{NO_DATA_PREFIX}No matching patterns found for: '{query}'"

        lines = [f"Pattern search: '{query}' ({len(results)} matches):"]
        for r in results:
            p = r.payload
            dt = r.data_type or p.get("data_type", "unknown")
            score = f" (relevance: {r.score:.2f})" if r.score else ""
            lines.append(f"  - [{dt}]{score} {_format_payload(p, names)}")

        return self._cap_result("\n".join(lines), self._panel_char_limit(patient_ids))

    async def _get_recent_insights(self, args: dict, patient_ids: list[str]) -> str:
        """Fetch recent proactive insights from InsightTracker."""
        from zoneinfo import ZoneInfo

        if not self._insight_tracker:
            return "No insight history available."
        limit = args.get("limit", 5)

        # Resolve patient timezone for timestamp display
        tz_name = settings.DEFAULT_PATIENT_TIMEZONE
        if patient_ids and self._patient_resolver:
            try:
                tzs = await self._patient_resolver.resolve_timezones(patient_ids[:1])
                tz_name = tzs.get(patient_ids[0], tz_name)
            except Exception:
                logger.warning("Timezone resolution failed for %s", patient_ids, exc_info=True)
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = timezone.utc

        all_insights: list[dict] = []
        unique_patient_ids = list(dict.fromkeys(patient_ids))
        history_tasks = [
            self._insight_tracker.get_history(pid, limit=limit)
            for pid in unique_patient_ids
        ]
        histories = await asyncio.gather(*history_tasks, return_exceptions=True)
        for history in histories:
            if isinstance(history, Exception):
                continue
            all_insights.extend(history)
        if not all_insights:
            return "No recent insights found for this patient."

        lines = ["Recent health insights (notifications):"]
        for ins in all_insights:
            created = ins.get("created_at")
            ts = ""
            if created:
                try:
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    local = created.astimezone(tz)
                    ts = f" (sent {local.strftime('%I:%M %p, %b %d').lstrip('0')})"
                except Exception:
                    pass
            lines.append(
                f"- [{ins.get('severity')}] {ins.get('title', 'Insight')}: "
                f"{ins.get('message', '')}{ts}"
            )
        return "\n".join(lines)

    async def _metabolic_profile(self, patient_ids: list[str]) -> str:
        if not self._metabolic:
            return f"{NO_DATA_PREFIX}Metabolic engine not available."
        if not patient_ids:
            return f"{NO_DATA_PREFIX}No patient ID provided."

        results: list[str] = []
        for pid in patient_ids[:5]:
            try:
                profile = await self._metabolic.risk_profile(pid)
                parts = []
                if profile.get("mmiq_tier"):
                    parts.append(f"Metabolic phenotype: {profile['mmiq_tier']}")
                if profile.get("mmiq_driver"):
                    parts.append(f"CGM driver: {profile['mmiq_driver']}")
                bmiq = profile.get("bmiq")
                if bmiq:
                    parts.append(f"BMIQ body comp: {bmiq}")
                wt = profile.get("weight_trend")
                if wt:
                    parts.append(f"Weight trend: {wt}")
                flags = profile.get("safety_flags")
                if flags:
                    parts.append(f"Safety flags: {flags}")
                pf = profile.get("patient_flags")
                if pf:
                    parts.append(f"Patient flags: {pf}")
                results.append(f"Patient {pid}: " + "; ".join(parts) if parts else f"Patient {pid}: insufficient data for metabolic profile")
            except Exception as exc:
                logger.warning("metabolic_profile failed for %s: %s", pid, exc)
                results.append(f"Patient {pid}: metabolic data unavailable")

        return "Metabolic Profile:\n" + "\n".join(results)

    # ── Formatting helpers ────────────────────────────────────────────────

    def _format_results(
        self,
        results: list[RetrievalResult],
        names: dict[str, str] | None = None,
        requested_types: list[str] | None = None,
        patient_ids: list[str] | None = None,
    ) -> str:
        """Format results as readable text grouped by data type.

        Groups are ordered by ``requested_types`` if provided, otherwise by
        first-seen order. Records within each group are sorted most-recent-first.
        The per-type record cap scales with patient count for panel queries.
        """
        from lib.ai_foundation.agents.health_query.result_ranking import _extract_time_key

        pids = patient_ids or []
        records_per_type = self._panel_records_per_type(pids)
        char_limit = self._panel_char_limit(pids)

        by_type: dict[str, list[dict]] = {}
        for r in results:
            dt = r.data_type or r.payload.get("data_type", "unknown")
            by_type.setdefault(dt, []).append(r.payload)

        # Determine section order: requested types first, then remaining
        if requested_types:
            ordered_keys = [dt for dt in requested_types if dt in by_type]
            ordered_keys += [dt for dt in by_type if dt not in ordered_keys]
        else:
            ordered_keys = list(by_type.keys())

        sections: list[str] = []
        for dt in ordered_keys:
            items = by_type[dt]
            # Sort within group: most recent first
            try:
                items.sort(key=lambda p: _extract_time_key(p), reverse=True)
            except (TypeError, ValueError):
                pass  # keep original order if sort fails on malformed payload

            label = dt.replace("_", " ").upper()
            lines: list[str] = [f"{label} ({len(items)} entries):"]
            for item in items[:records_per_type]:
                lines.append("  - " + _format_payload(item, names, include_nested=True))

            if len(items) > records_per_type:
                lines.append(f"  ... and {len(items) - records_per_type} more")

            sections.append("\n".join(lines))

        return self._cap_result("\n\n".join(sections), char_limit)

    @staticmethod
    def _cap_result(text: str, max_chars: int | None = None) -> str:
        """Cap tool result to prevent context bloat. Truncates at line boundaries."""
        from lib.ai_foundation.agents.health_query.result_ranking import cap_at_record_boundaries
        limit = max_chars if max_chars is not None else settings.REASONING_MAX_TOOL_RESULT_CHARS
        return cap_at_record_boundaries(text, limit)
