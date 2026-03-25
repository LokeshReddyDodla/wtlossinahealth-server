"""
Health Data Service — personalized data fetching with context enrichment.

Every query gets enriched with the patient's history so the LLM can give
personalized answers, not generic population-level responses.

"Show fitness today" → today's data + 30-day baseline + profile
"Suggest meals" → recent meals + glucose patterns + profile + preferences
"How is glucose?" → glucose data + related meals + profile
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from lib.ai_foundation.config import settings
from lib.ai_foundation.retrieval.base import RetrievalRequest, RetrievalResult

if TYPE_CHECKING:
    from lib.ai_foundation.retrieval.qdrant import QdrantRetriever
    from lib.ai_foundation.retrieval.patient_summary import PatientSummaryRetriever
    from lib.ai_foundation.agents.health_query.contracts import QueryIntent

logger = logging.getLogger(__name__)

# Which domains are related — used for automatic enrichment
_RELATED_DOMAINS: dict[str, list[str]] = {
    "meal": ["cgm_range_stats", "cgm_summary_stats"],          # meals affect glucose
    "cgm_range_stats": ["meal"],                                 # glucose correlates with meals
    "cgm_summary_stats": ["meal"],
    "fitness_overview": ["cgm_range_stats"],                     # exercise affects glucose
    "hypo_stats": ["meal", "fitness_overview"],                  # hypos can be caused by meals/exercise
    "hypo_event": ["meal", "fitness_overview"],
    "rapid_spike_stats": ["meal"],                               # spikes usually from meals
    "rapid_spike_event": ["meal"],
}

_BASELINE_DAYS = 30  # how many days of history to fetch for baseline comparison


class HealthDataService:
    """Personalized data fetching — always includes context for comparison.

    Three layers of data per query:
    1. Primary: exactly what the user asked for
    2. Baseline: last 30 days of the same data type (for comparison)
    3. Related: cross-domain data that helps explain patterns
    + Profile is always included for personalization
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
        """Fetch data with full personalization context.

        Returns formatted text ready for the LLM, including:
        - Primary data (what was asked)
        - Baseline (30-day history for comparison)
        - Related domains (for cross-domain insights)
        - Patient profile (always)
        """
        if not self._qdrant:
            return "No data source available."

        # Run all fetches in parallel
        primary_task = self._fetch_primary(intent, patient_ids)
        baseline_task = self._fetch_baseline(intent, patient_ids)
        related_task = self._fetch_related(intent, patient_ids)
        profile_task = self._fetch_profile(patient_ids)

        primary, baseline, related, profile = await asyncio.gather(
            primary_task, baseline_task, related_task, profile_task,
        )

        # Enrich with patient_summary for sleep if needed
        if self._summary and self._needs_sleep_enrichment(intent, primary):
            try:
                request = self._build_request(intent, patient_ids)
                summary_results = await self._summary.retrieve(request)
                primary.extend(summary_results)
            except Exception:
                pass

        # Format all layers into readable text
        return self._format_all(primary, baseline, related, profile)

    # -- Primary fetch (what the user asked) --------------------------------

    async def _fetch_primary(
        self, intent: QueryIntent, patient_ids: list[str],
    ) -> list[RetrievalResult]:
        """Fetch exactly what the user asked for."""
        request = self._build_request(intent, patient_ids)
        if self._is_deterministic(intent):
            return await self._qdrant.retrieve_filtered(request)
        else:
            request.query = intent.clarification_msg or "health data query"
            return await self._qdrant.retrieve(request)

    # -- Baseline fetch (history for comparison) ----------------------------

    async def _fetch_baseline(
        self, intent: QueryIntent, patient_ids: list[str],
    ) -> list[RetrievalResult]:
        """Fetch last 30 days of the same data types for baseline comparison.

        Skipped if the query already spans 14+ days (it IS the baseline).
        """
        if not intent.data_types:
            return []

        # Don't fetch baseline if the query already covers a long period
        if intent.date_range:
            span = (intent.date_range.end - intent.date_range.start).days
            if span >= 14:
                return []

        # Don't fetch baseline for profile queries
        type_values = [dt.value for dt in intent.data_types]
        if all(t in ("profile", "patient_document") for t in type_values):
            return []

        now = datetime.now(timezone.utc)
        baseline_start = (now - timedelta(days=_BASELINE_DAYS)).isoformat()

        try:
            request = RetrievalRequest(
                query="",
                patient_ids=patient_ids,
                data_types=type_values,
                date_start=baseline_start,
                date_end=now.isoformat(),
                limit=20,  # enough for averages, not too much for context
            )
            return await self._qdrant.retrieve_filtered(request)
        except Exception:
            return []

    # -- Related domains fetch (cross-domain context) -----------------------

    async def _fetch_related(
        self, intent: QueryIntent, patient_ids: list[str],
    ) -> list[RetrievalResult]:
        """Fetch related domain data for cross-domain insights.

        If asking about glucose → also fetch recent meals.
        If asking about meals → also fetch recent glucose.
        If asking about fitness → also fetch recent glucose.
        """
        if not intent.data_types or not intent.date_range:
            return []

        # Collect related data types
        related_types: set[str] = set()
        primary_types = {dt.value for dt in intent.data_types}
        for dt_value in primary_types:
            for related in _RELATED_DOMAINS.get(dt_value, []):
                if related not in primary_types:  # don't re-fetch primary types
                    related_types.add(related)

        if not related_types:
            return []

        try:
            request = RetrievalRequest(
                query="",
                patient_ids=patient_ids,
                data_types=list(related_types),
                date_start=intent.date_range.start.isoformat() if intent.date_range else None,
                date_end=intent.date_range.end.isoformat() if intent.date_range else None,
                limit=10,  # just enough for context, not overwhelming
            )
            return await self._qdrant.retrieve_filtered(request)
        except Exception:
            return []

    # -- Profile fetch (always) ---------------------------------------------

    async def _fetch_profile(self, patient_ids: list[str]) -> list[RetrievalResult]:
        """Always fetch patient profile for personalization context."""
        if not patient_ids:
            return []

        try:
            request = RetrievalRequest(
                query="",
                patient_ids=patient_ids,
                data_types=["profile"],
                limit=len(patient_ids),  # one profile per patient
            )
            return await self._qdrant.retrieve_filtered(request)
        except Exception:
            return []

    # -- Request building ---------------------------------------------------

    @staticmethod
    def _build_request(intent: QueryIntent, patient_ids: list[str]) -> RetrievalRequest:
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
            query="",
            patient_ids=patient_ids,
            data_types=[dt.value for dt in intent.data_types],
            date_start=intent.date_range.start.isoformat() if intent.date_range else None,
            date_end=intent.date_range.end.isoformat() if intent.date_range else None,
            limit=settings.QDRANT_RESULT_LIMIT,
            filters=filters,
        )

    # -- Helpers ------------------------------------------------------------

    @staticmethod
    def _is_deterministic(intent: QueryIntent) -> bool:
        return bool(intent.data_types)

    @staticmethod
    def _needs_sleep_enrichment(intent: QueryIntent, results: list[RetrievalResult]) -> bool:
        requested = {dt.value for dt in intent.data_types}
        if not {"sleep", "sleep_report"}.intersection(requested):
            return False
        result_types = {r.data_type for r in results if r.data_type}
        return not {"sleep", "sleep_report"}.intersection(result_types)

    # -- Formatting ---------------------------------------------------------

    @staticmethod
    def _format_all(
        primary: list[RetrievalResult],
        baseline: list[RetrievalResult],
        related: list[RetrievalResult],
        profile: list[RetrievalResult],
    ) -> str:
        """Format all data layers into readable text for the LLM."""
        sections: list[str] = []

        # Profile first (personalization context)
        if profile:
            profile_text = HealthDataService._format_results(profile, "PATIENT PROFILE")
            if profile_text:
                sections.append(profile_text)

        # Primary data (what was asked)
        if primary:
            primary_text = HealthDataService._format_results(primary, "CURRENT DATA (what was asked)")
            if primary_text:
                sections.append(primary_text)

        # Baseline (history for comparison)
        if baseline:
            baseline_text = HealthDataService._format_results(baseline, "BASELINE (last 30 days for comparison)")
            if baseline_text:
                sections.append(baseline_text)

        # Related domains
        if related:
            related_text = HealthDataService._format_results(related, "RELATED DATA (for cross-domain insights)")
            if related_text:
                sections.append(related_text)

        if not sections:
            return "No health data found for this query."

        return "\n\n".join(sections)

    @staticmethod
    def _format_results(results: list[RetrievalResult], header: str) -> str:
        """Format a list of results into readable text."""
        by_type: dict[str, list[dict]] = {}
        for r in results:
            dt = r.data_type or r.payload.get("data_type", "unknown")
            by_type.setdefault(dt, []).append(r.payload)

        lines: list[str] = [f"=== {header} ==="]
        for dt, items in by_type.items():
            label = dt.replace("_", " ").upper()
            lines.append(f"\n{label} ({len(items)} entries):")

            for item in items[:settings.MAX_RECORDS_PER_TYPE]:
                clean = {
                    k: v for k, v in item.items()
                    if k not in ("data_type", "source", "patient_id", "embedding") and v is not None
                }
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

        return "\n".join(lines)
