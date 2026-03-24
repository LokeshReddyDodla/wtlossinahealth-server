"""
Health Data Service — single entry point for all data fetching.

Routes queries to Qdrant filtered scroll (deterministic) or semantic search
(cross-domain). Formats retrieved data into clean text for the LLM.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from lib.ai_foundation.retrieval.base import RetrievalRequest, RetrievalResult

if TYPE_CHECKING:
    from lib.ai_foundation.retrieval.qdrant import QdrantRetriever
    from lib.ai_foundation.retrieval.patient_summary import PatientSummaryRetriever
    from lib.ai_foundation.agents.health_query.contracts import QueryIntent

logger = logging.getLogger(__name__)

_MAX_RECORDS_PER_TYPE = 10  # cap per data_type to keep LLM context manageable


class HealthDataService:
    """Fetches health data from Qdrant and formats it for the LLM.

    Two modes:
    - Filtered scroll: deterministic queries (specific data_types + date range)
    - Semantic search: cross-domain pattern queries
    """

    def __init__(
        self,
        *,
        qdrant_retriever: QdrantRetriever | None = None,
        summary_retriever: PatientSummaryRetriever | None = None,
    ) -> None:
        self._qdrant = qdrant_retriever
        self._summary = summary_retriever

    async def fetch(
        self,
        intent: QueryIntent,
        patient_ids: list[str],
    ) -> str:
        """Fetch data and return formatted text ready for the LLM.

        Returns a human-readable string, not raw dicts or JSON.
        The LLM receives this directly and uses it to generate the response.
        """
        if not self._qdrant:
            return "No data source available."

        request = self._build_request(intent, patient_ids)
        results = await self._execute(intent, request)

        # Enrich with patient_summary for sleep if needed
        if self._summary and self._needs_sleep_enrichment(intent, results):
            try:
                summary_results = await self._summary.retrieve(request)
                results.extend(summary_results)
            except Exception as exc:
                logger.debug("Summary enrichment failed: %s", exc)

        if not results:
            return "No health data found for this query."

        return self._format_for_llm(results)

    # -- Request building --------------------------------------------------

    @staticmethod
    def _build_request(intent: QueryIntent, patient_ids: list[str]) -> RetrievalRequest:
        """Build RetrievalRequest with all filters from intent."""
        filters: dict[str, Any] = {}
        if intent.time_buckets:
            filters["time_buckets"] = intent.time_buckets
        if intent.hour_range and intent.hour_range.start_hour is not None:
            filters["hour_start"] = intent.hour_range.start_hour
            filters["hour_end"] = intent.hour_range.end_hour
        if intent.month_filters:
            filters["month_filters"] = intent.month_filters
        if intent.numeric_filters:
            filters["numeric_filters"] = [
                {"key": nf.key, "range_condition": nf.range_condition.model_dump(exclude_none=True)}
                for nf in intent.numeric_filters
            ]

        return RetrievalRequest(
            query="",  # only used for semantic search embedding
            patient_ids=patient_ids,
            data_types=[dt.value for dt in intent.data_types],
            date_start=intent.date_range.start.isoformat() if intent.date_range else None,
            date_end=intent.date_range.end.isoformat() if intent.date_range else None,
            limit=30,
            filters=filters,
        )

    # -- Execution ---------------------------------------------------------

    async def _execute(
        self, intent: QueryIntent, request: RetrievalRequest,
    ) -> list[RetrievalResult]:
        """Route to the right retrieval mode."""
        if self._is_deterministic(intent):
            results = await self._qdrant.retrieve_filtered(request)
        else:
            request.query = intent.clarification_msg or "health data query"
            results = await self._qdrant.retrieve(request)

        logger.debug("Data fetch: %d results, mode=%s",
                     len(results), "filtered" if self._is_deterministic(intent) else "semantic")
        return results

    @staticmethod
    def _is_deterministic(intent: QueryIntent) -> bool:
        """Deterministic = specific data_types exist. Semantic = vague/no types."""
        return bool(intent.data_types)

    @staticmethod
    def _needs_sleep_enrichment(intent: QueryIntent, results: list[RetrievalResult]) -> bool:
        """Sleep is not in Qdrant — needs patient_summary fallback."""
        requested = {dt.value for dt in intent.data_types}
        if not {"sleep", "sleep_report"}.intersection(requested):
            return False
        result_types = {r.data_type for r in results if r.data_type}
        return not {"sleep", "sleep_report"}.intersection(result_types)

    # -- Formatting for LLM ------------------------------------------------

    @staticmethod
    def _format_for_llm(results: list[RetrievalResult]) -> str:
        """Format retrieved data as clean readable text.

        No hardcoded field names. Groups by data_type, strips internal
        fields, flattens one level of nesting, caps per type.
        The LLM interprets the values and presents them naturally.
        """
        by_type: dict[str, list[dict]] = {}
        for r in results:
            dt = r.data_type or r.payload.get("data_type", "unknown")
            by_type.setdefault(dt, []).append(r.payload)

        sections: list[str] = []
        for dt, items in by_type.items():
            label = dt.replace("_", " ").upper()
            lines: list[str] = []

            for item in items[:_MAX_RECORDS_PER_TYPE]:
                # Strip internal fields, keep everything the LLM should see
                clean = {
                    k: v for k, v in item.items()
                    if k not in ("data_type", "source", "patient_id", "embedding") and v is not None
                }
                # Flatten one level of nesting
                parts: list[str] = []
                for k, v in clean.items():
                    if isinstance(v, dict):
                        inner = ", ".join(f"{ik}: {iv}" for ik, iv in v.items() if iv is not None)
                        if inner:
                            parts.append(f"{k}: ({inner})")
                    elif isinstance(v, list) and v and isinstance(v[0], dict):
                        # List of dicts (e.g., food_items) — show count
                        parts.append(f"{k}: {len(v)} items")
                    else:
                        parts.append(f"{k}: {v}")

                lines.append("  - " + ", ".join(parts))

            if len(items) > _MAX_RECORDS_PER_TYPE:
                lines.append(f"  ... and {len(items) - _MAX_RECORDS_PER_TYPE} more")

            sections.append(f"{label} ({len(items)} entries):\n" + "\n".join(lines))

        return "\n\n".join(sections)
