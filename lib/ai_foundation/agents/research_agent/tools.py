"""
Research Agent — cohort tools.

Six tools that the executor picks between based on the planner's ``CohortSpec``:

    find_cohort         — identify patients with a condition
    cohort_aggregate    — count / facet / distribution across patients
    cohort_match        — patients matching one criterion → ID list
    cohort_intersect    — multi-criterion AND/OR/NOT → ID list + funnel
    rank_cohort         — top-K patients by a precomputed criterion
    summarize_patient   — per-patient summary (delegates to health_query)

These tools are deliberately self-contained — they talk to ``QdrantStore``
and ``MongoStore`` directly via the standard Qdrant async client API rather
than going through ``lib/ai_foundation/retrieval/qdrant.py``'s
``QdrantRetriever``. This keeps the existing retrieval module untouched
while we are in Phase 1; the long-term plan is to push these aggregations
down into the foundation later (see ``research_agent_plan.md`` Phase 0).

Tools never return raw records to the LLM. They return:

    - a count (cohort_aggregate)
    - a small list of IDs (cohort_match, cohort_intersect)
    - up to ~5 sample scorecard / aggregated rows (rank_cohort)
    - a structured per-patient summary (summarize_patient)

That bounded result size is what lets cohort questions scale to thousands
of patients without context-window pressure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    Range,
)

from .contracts import (
    CohortCombinator,
    Criterion,
    ExecutionResult,
    ExecutionResultKind,
    FunnelStep,
)

logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────────

# Hard caps to keep tool results bounded regardless of cohort size.
MAX_IDS_RETURNED = 50_000              # cohort_match ceiling
MAX_SCROLL_BATCH = 1_000               # per-page scroll size
MAX_SAMPLE_ROWS = 5                    # rows the LLM ever sees per tool
TOOL_QUERY_TIMEOUT_SECONDS = 30.0      # per Qdrant/Mongo call


# Window strings the planner is allowed to emit.
_WINDOW_TO_DAYS: dict[str, int | None] = {
    "1d": 1, "3d": 3, "7d": 7, "14d": 14,
    "30d": 30, "60d": 60, "90d": 90,
    # Longer windows for "in the last 6 months" / "this year" / "in 2026"
    "180d": 180, "1y": 365, "365d": 365,
    "all": None,
}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _window_to_epoch_ms_range(window: str) -> tuple[int | None, int | None]:
    """Convert ``'7d'`` / ``'30d'`` / ``'all'`` to a (start_ms, end_ms) range.

    Returns (None, None) for ``'all'``. ``end_ms`` is always None (open-ended
    to "now") so we don't accidentally drop today's data.
    """
    days = _WINDOW_TO_DAYS.get(window)
    if days is None:
        return None, None
    start_dt = datetime.now(timezone.utc) - timedelta(days=days)
    return int(start_dt.timestamp() * 1000), None


def _build_qdrant_filter(
    patient_ids: list[str],
    data_type: str,
    window: str,
    extra_filter: dict[str, Any] | None = None,
) -> Filter:
    """Build a Qdrant ``Filter`` for (patient_ids ∩ data_type ∩ time-range ∩ extras).

    ``extra_filter`` keys are interpreted as either:
      - {key: {"lt"|"lte"|"gt"|"gte": number}} → Range condition
      - {key: scalar} → MatchValue
      - {key: [list]} → MatchAny

    Unsupported / unknown shapes are skipped with a warning.
    """
    must: list[Any] = [
        FieldCondition(key="patient_id", match=MatchAny(any=patient_ids)),
        FieldCondition(key="data_type", match=MatchValue(value=data_type)),
    ]

    start_ms, end_ms = _window_to_epoch_ms_range(window)
    if start_ms is not None:
        must.append(FieldCondition(key="start_time", range=Range(gte=start_ms)))
    if end_ms is not None:
        must.append(FieldCondition(key="end_time", range=Range(lte=end_ms)))

    for key, condition in (extra_filter or {}).items():
        if isinstance(condition, dict):
            range_kwargs = {
                k: condition[k] for k in ("gt", "gte", "lt", "lte") if k in condition
            }
            if range_kwargs:
                must.append(FieldCondition(key=key, range=Range(**range_kwargs)))
                continue
            logger.warning("Skipping unsupported filter shape for key=%s: %s", key, condition)
        elif isinstance(condition, list):
            must.append(FieldCondition(key=key, match=MatchAny(any=condition)))
        else:
            must.append(FieldCondition(key=key, match=MatchValue(value=condition)))

    return Filter(must=must)


def _label_for(criterion: Criterion) -> str:
    """Auto-generate a human-readable label for a criterion (for funnel narration)."""
    if criterion.label:
        return criterion.label
    base = f"{criterion.data_type}"
    if criterion.window and criterion.window != "all":
        base += f" last {criterion.window}"
    if criterion.filter:
        parts = []
        for key, cond in criterion.filter.items():
            if isinstance(cond, dict):
                op_str = ", ".join(f"{k}={v}" for k, v in cond.items())
                parts.append(f"{key} {op_str}")
            else:
                parts.append(f"{key}={cond}")
        if parts:
            base += f" where {' & '.join(parts)}"
    return base


# ── Tools ────────────────────────────────────────────────────────────────────


@dataclass
class CohortTools:
    """Bundle of cohort tools with their data-layer dependencies.

    Constructed once per request by ``CohortExecutor``. Holds:
      - ``qdrant_store``: lib.core.qdrant_store.QdrantStore (foundation client)
      - ``qdrant_collection``: name of the Qdrant collection (defaults to "patient_data")
      - ``mongo_store``: lib.core.mongo_store.MongoStore
      - ``embed_fn``: optional async callable text→vector for ``find_cohort`` semantic fallback
      - ``patient_name_resolver``: optional; if supplied, ID-returning tools enrich
        their results with patient names so the responder can list them by name.
      - ``health_query_agent``: optional, used by ``summarize_patient`` to delegate per-patient work

    All dependencies are passed in rather than resolved from the container
    inside the tools — keeps this module testable and side-effect-free.
    """

    qdrant_store: Any
    mongo_store: Any
    qdrant_collection: str = "patient_data"
    embed_fn: Any | None = None
    patient_name_resolver: Any | None = None
    health_query_agent: Any | None = None

    # Up to this many patients get name-resolved per tool call. Keeps
    # responder payloads small even on 1000-patient cohorts.
    name_enrich_limit: int = 25

    async def resolve_names(self, patient_ids: list[str]) -> list[dict[str, str]]:
        """Look up names for ``patient_ids`` (capped at ``name_enrich_limit``).

        Returns a list of ``{"patient_id", "name"}`` rows in the same order
        as the input. If no resolver is wired, returns rows with stub names
        derived from the UUID prefix so the responder still has something
        to narrate.
        """
        if not patient_ids:
            return []
        capped = patient_ids[: self.name_enrich_limit]
        if self.patient_name_resolver is None:
            return [
                {"patient_id": pid, "name": f"Patient {pid[:8]}"}
                for pid in capped
            ]
        try:
            name_by_id = await self.patient_name_resolver.resolve_names(capped)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("resolve_names failed: %s", exc)
            name_by_id = {}
        return [
            {"patient_id": pid, "name": name_by_id.get(pid, f"Patient {pid[:8]}")}
            for pid in capped
        ]

    # ── cohort_aggregate ───────────────────────────────────────────────

    async def cohort_aggregate(
        self,
        *,
        cohort_ids: list[str],
        data_type: str,
        metric: str = "count_unique_patients",
        window: str = "7d",
        extra_filter: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Count / distribution. Returns a small dict, never records.

        Metrics:
            count_unique_patients — number of distinct patient_ids matching
            count_records         — number of matching records
            facet:<field>         — group-by on a payload field, returns top-N buckets

        Implementation note: Qdrant has no native DISTINCT, so unique-patient
        counts scroll IDs and dedupe in Python. Bounded by ``MAX_IDS_RETURNED``.
        """
        if not cohort_ids:
            return {"patient_count": 0, "total_records": 0}

        # Special metric — survey known condition signatures across the cohort.
        # Doesn't need a data_type; the helper iterates the signature table.
        if metric == "condition_distribution":
            return await self.condition_distribution(cohort_ids=cohort_ids)

        qfilter = _build_qdrant_filter(cohort_ids, data_type, window, extra_filter)

        if metric == "count_records":
            return {"total_records": await self._qdrant_count(qfilter)}

        if metric.startswith("facet:"):
            field = metric.split(":", 1)[1]
            return await self._qdrant_facet(qfilter, field)

        # Default: count_unique_patients
        ids = await self._qdrant_scroll_patient_ids(qfilter)
        unique = sorted(set(ids))
        return {
            "patient_count": len(unique),
            "total_records": len(ids),
        }

    # ── cohort_match ───────────────────────────────────────────────────

    async def cohort_match(
        self,
        *,
        cohort_ids: list[str],
        data_type: str,
        window: str = "7d",
        extra_filter: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return patient IDs matching one criterion. No record content.

        Capped at ``MAX_IDS_RETURNED``. If the result hits the cap, the
        caller should treat the result as truncated.
        """
        if not cohort_ids:
            return {"matched_ids": [], "count": 0, "truncated": False}

        qfilter = _build_qdrant_filter(cohort_ids, data_type, window, extra_filter)
        raw_ids = await self._qdrant_scroll_patient_ids(qfilter)
        unique = sorted(set(raw_ids))
        truncated = len(unique) >= MAX_IDS_RETURNED
        return {
            "matched_ids": unique[:MAX_IDS_RETURNED],
            "count": len(unique),
            "truncated": truncated,
        }

    # ── cohort_intersect ───────────────────────────────────────────────

    async def cohort_intersect(
        self,
        *,
        cohort_ids: list[str],
        criteria: list[Criterion],
        combinator: CohortCombinator = CohortCombinator.AND,
    ) -> ExecutionResult:
        """Multi-criterion intersection with funnel narration.

        Phase 1 always uses the Qdrant fallback path — scorecards don't
        exist yet, so we run one ``cohort_match`` per criterion and
        intersect/union in code. Funnel is emitted as we go.

        AND  : running = running ∩ ids
        OR   : running = running ∪ ids
        NOT  : running = running − ids   (interpreted per-step, applied left-to-right)
        """
        funnel: list[FunnelStep] = [FunnelStep(step="cohort", count=len(cohort_ids))]
        running: set[str] = set(cohort_ids)

        for criterion in criteria:
            ids_set: set[str]
            # Scope each match to the patients still in the running set —
            # this keeps the per-step Qdrant filter small as we narrow.
            scope = list(running) if running else list(cohort_ids)
            match_result = await self.cohort_match(
                cohort_ids=scope,
                data_type=criterion.data_type,
                window=criterion.window,
                extra_filter=criterion.filter,
            )
            ids_set = set(match_result["matched_ids"])

            if combinator == CohortCombinator.AND:
                running = running & ids_set
            elif combinator == CohortCombinator.OR:
                running = running | ids_set
            elif combinator == CohortCombinator.NOT:
                # NOT here is "exclude patients matching this criterion."
                running = running - ids_set
            else:
                raise ValueError(f"Unsupported combinator: {combinator}")

            funnel.append(FunnelStep(step=_label_for(criterion), count=len(running)))

        final_ids = sorted(running)
        return ExecutionResult(
            kind=ExecutionResultKind.INLINE,
            funnel=funnel,
            final_ids=final_ids,
            final_count=len(final_ids),
            sample_rows=[],
            path="qdrant_fallback",
        )

    # ── find_cohort ────────────────────────────────────────────────────

    async def find_cohort(
        self,
        *,
        condition: str,
        provider_patient_ids: list[str],
    ) -> dict[str, Any]:
        """Identify patients with a given condition.

        Three-source lookup (each contributes patient IDs; the union is returned):

          1. **Structured tags** — ``ai_patient_memory`` where ``category=condition``
             and ``key`` matches the condition (or one of its synonyms).

          2. **Data-type signatures** — for conditions whose presence is strongly
             implied by the existence of certain clinical data types, scan those
             data types in Qdrant and collect the patient_ids that have any such
             records in the last 180 days. Example:

                 diabetes → has CGM data / hypo events / hyper events / SMBG readings
                 hypertension → has blood-pressure vitals (currently no payload filter)

             This is what answers the user's natural-language intent: "diabetes
             patients" should resolve to "patients with glucose data," not just
             patients with a literal `diabetes` tag.

          3. **Semantic search** — Qdrant vector search across ``symptom_entry``
             and ``patient_document`` for free-text mentions of the condition.
             Only runs when ``embed_fn`` is configured.

        Returns ``{"count", "ids", "sources": {"by_tag", "by_signature", "by_search"}}``.
        ``sources`` counts are disjoint — each patient is attributed to the
        first (highest-trust) source that found them.
        """
        if not provider_patient_ids:
            return {
                "count": 0,
                "ids": [],
                "sources": {"by_tag": 0, "by_signature": 0, "by_search": 0},
            }

        # Source 1 — structured condition tags in ai_patient_memory.
        by_tag = set(
            await self._mongo_find_condition_patients(
                patient_ids=provider_patient_ids,
                condition=condition,
            )
        )

        # Source 2 — clinical data-type signatures for known conditions.
        by_signature: set[str] = set()
        signature_types = _CONDITION_DATA_SIGNATURES.get(_normalize_condition(condition), [])
        if signature_types:
            try:
                # 1-year window: signatures are "has ever shown the clinical
                # data pattern" — recent enough to be relevant, broad enough
                # that legacy data doesn't disappear from view.
                by_signature = await self._qdrant_signature_patients(
                    patient_ids=provider_patient_ids,
                    data_types=signature_types,
                    window="1y",
                )
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning("find_cohort signature search failed: %s", exc)

        # Source 3 — semantic search (only if embed_fn was supplied).
        by_search: set[str] = set()
        if self.embed_fn is not None:
            try:
                by_search = await self._qdrant_semantic_condition_search(
                    patient_ids=provider_patient_ids,
                    condition=condition,
                )
            except Exception as exc:  # pragma: no cover — semantic path is best-effort
                logger.warning("find_cohort semantic fallback failed: %s", exc)

        # Attribute each patient to the highest-trust source that found them.
        # tag (clinician-entered) > signature (clinical data inference) > search (notes).
        only_signature = by_signature - by_tag
        only_search = by_search - by_tag - by_signature

        all_ids = sorted(by_tag | by_signature | by_search)
        return {
            "count": len(all_ids),
            "ids": all_ids,
            "sources": {
                "by_tag": len(by_tag),
                "by_signature": len(only_signature),
                "by_search": len(only_search),
            },
            "signature_data_types": signature_types,
        }

    # ── rank_cohort ────────────────────────────────────────────────────

    async def rank_cohort(
        self,
        *,
        cohort_ids: list[str],
        criterion: str,
        k: int = 20,
    ) -> ExecutionResult:
        """Top-K patients by a precomputed criterion.

        Phase 1: scorecards don't exist yet, so this returns a NOT_IMPLEMENTED
        ExecutionResult with a clear reason. The responder narrates that
        ranking will be available once the daily scorecard scan ships.

        Phase 2 fills this in by reading from ``ai_patient_scorecard``.
        """
        return ExecutionResult(
            kind=ExecutionResultKind.NOT_IMPLEMENTED,
            reason=(
                "rank_cohort requires the patient scorecard collection, which "
                "is not built yet (see research_agent_plan.md Phase 1 scorecard "
                f"scan). Asked for top-{k} by '{criterion}' over {len(cohort_ids)} patients."
            ),
        )

    # ── summarize_patient ──────────────────────────────────────────────

    async def summarize_patient(
        self,
        *,
        patient_id: str,
        focus: str,
    ) -> dict[str, Any]:
        """Per-patient summary — delegates to the existing health_query agent.

        Phase 1: this requires the caller to have provided a ``health_query_agent``
        when constructing CohortTools. If not, returns a NOT_IMPLEMENTED result
        so the executor can fall back to a "no per-patient detail in this phase"
        narration. We deliberately do not duplicate single-patient reasoning here.
        """
        if self.health_query_agent is None:
            return {
                "ok": False,
                "reason": (
                    "summarize_patient requires HealthQueryAgent wiring (delegation). "
                    "Pass health_query_agent= when constructing CohortTools."
                ),
            }
        # Intentionally generic — the wiring details are settled in Phase 2 once
        # we lock the delegation contract (input shape + summary format).
        return {
            "ok": False,
            "reason": "summarize_patient delegation contract pending Phase 2 design.",
            "patient_id": patient_id,
            "focus": focus,
        }

    # ── Internal Qdrant helpers ────────────────────────────────────────

    async def _qdrant_count(self, qfilter: Filter) -> int:
        """Run Qdrant's ``count`` API. Returns the matching record count."""
        async with self.qdrant_store.get_client() as client:
            result = await client.count(
                collection_name=self.qdrant_collection,
                count_filter=qfilter,
                exact=True,
            )
        return int(result.count)

    async def _qdrant_scroll_patient_ids(self, qfilter: Filter) -> list[str]:
        """Scroll a filter, return only the patient_id payload field.

        Pages through the result with the standard Qdrant scroll pattern.
        Bounded by ``MAX_IDS_RETURNED`` to keep memory predictable.
        """
        ids: list[str] = []
        next_offset = None
        async with self.qdrant_store.get_client() as client:
            while True:
                points, next_offset = await client.scroll(
                    collection_name=self.qdrant_collection,
                    scroll_filter=qfilter,
                    limit=MAX_SCROLL_BATCH,
                    offset=next_offset,
                    with_payload=["patient_id"],
                    with_vectors=False,
                )
                for point in points:
                    payload = point.payload or {}
                    pid = payload.get("patient_id")
                    if pid:
                        ids.append(str(pid))
                        if len(ids) >= MAX_IDS_RETURNED:
                            return ids
                if next_offset is None:
                    break
        return ids

    async def _qdrant_facet(
        self,
        qfilter: Filter,
        field: str,
    ) -> dict[str, Any]:
        """Group-by on a payload field. Returns top-N buckets.

        Implemented as a scroll + in-Python tally because Qdrant's native
        facet API surface is version-dependent. The implementation is bounded
        by ``MAX_IDS_RETURNED`` records — acceptable for cohort-size queries.
        """
        from collections import Counter
        counts: Counter[str] = Counter()
        scanned = 0
        next_offset = None
        async with self.qdrant_store.get_client() as client:
            while True:
                points, next_offset = await client.scroll(
                    collection_name=self.qdrant_collection,
                    scroll_filter=qfilter,
                    limit=MAX_SCROLL_BATCH,
                    offset=next_offset,
                    with_payload=[field],
                    with_vectors=False,
                )
                for point in points:
                    payload = point.payload or {}
                    value = payload.get(field)
                    if value is None:
                        continue
                    counts[str(value)] += 1
                    scanned += 1
                    if scanned >= MAX_IDS_RETURNED:
                        next_offset = None
                        break
                if next_offset is None:
                    break
        top = counts.most_common(20)
        return {
            "field": field,
            "total_records": scanned,
            "buckets": [{"value": v, "count": c} for v, c in top],
        }

    async def condition_distribution(
        self,
        *,
        cohort_ids: list[str],
    ) -> dict[str, Any]:
        """Survey every known condition signature across the cohort.

        For each condition in ``_CONDITION_DATA_SIGNATURES`` with a non-empty
        signature list, count how many patients have any matching record in
        the last 180 days. Returns the buckets sorted by count desc, plus
        a panel-wide total.

        This is what backs the "what conditions exist in my panel" question.
        Without this path, the `aggregate` intent has no way to surface
        signature-based detections — only formal condition codes (which the
        local dataset doesn't have).
        """
        if not cohort_ids:
            return {"total_patients": 0, "buckets": []}

        buckets: list[dict[str, Any]] = []
        for cond, signatures in _CONDITION_DATA_SIGNATURES.items():
            if not signatures:
                continue
            try:
                # Match find_cohort's window so the survey is consistent.
                pts = await self._qdrant_signature_patients(
                    patient_ids=cohort_ids,
                    data_types=signatures,
                    window="1y",
                )
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning("condition_distribution scan failed for %s: %s", cond, exc)
                pts = set()
            buckets.append({
                "condition": cond,
                "patient_count": len(pts),
                "data_types_checked": list(signatures),
            })

        buckets.sort(key=lambda b: b["patient_count"], reverse=True)
        return {
            "total_patients": len(cohort_ids),
            "buckets": buckets,
        }

    async def _qdrant_signature_patients(
        self,
        *,
        patient_ids: list[str],
        data_types: list[str],
        window: str,
    ) -> set[str]:
        """Scan multiple data types in parallel for any matching records.

        Returns the deduped set of patient_ids that have at least one record
        of any of ``data_types`` in the time window. Used by ``find_cohort``'s
        signature-based search.

        Why one filter per data_type rather than one filter with MatchAny on
        data_type: Qdrant's payload indices are tuned per-field and per-data-type
        scrolling is what existing retrieval code does. Keeping each call narrow
        also lets the scroll early-exit fast on data types where the cohort has
        plenty of activity (e.g. CGM for diabetes).
        """
        out: set[str] = set()
        for data_type in data_types:
            qfilter = _build_qdrant_filter(
                patient_ids=patient_ids,
                data_type=data_type,
                window=window,
            )
            try:
                ids = await self._qdrant_scroll_patient_ids(qfilter)
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning(
                    "signature scan failed for data_type=%s: %s", data_type, exc
                )
                continue
            out.update(ids)
            # If we already covered the entire input cohort, no need to keep scanning.
            if len(out) >= len(patient_ids):
                break
        return out

    async def _qdrant_semantic_condition_search(
        self,
        *,
        patient_ids: list[str],
        condition: str,
    ) -> set[str]:
        """Best-effort: embed the condition text, semantic-search Qdrant for it.

        Restricted to ``symptom_entry`` / ``patient_document`` data types and
        scoped to ``patient_ids``. Returns the deduped set of patient_ids
        whose top hits exceed the score threshold.
        """
        vector = await self.embed_fn(condition)  # type: ignore[misc]
        qfilter = Filter(
            must=[
                FieldCondition(key="patient_id", match=MatchAny(any=patient_ids)),
                FieldCondition(
                    key="data_type",
                    match=MatchAny(any=["symptom_entry", "patient_document"]),
                ),
            ]
        )
        async with self.qdrant_store.get_client() as client:
            hits = await client.search(
                collection_name=self.qdrant_collection,
                query_vector=vector,
                query_filter=qfilter,
                limit=2000,
                score_threshold=0.78,
                with_payload=["patient_id"],
            )
        out: set[str] = set()
        for hit in hits:
            payload = hit.payload or {}
            pid = payload.get("patient_id")
            if pid:
                out.add(str(pid))
        return out

    # ── Internal Mongo helpers ─────────────────────────────────────────

    async def _mongo_find_condition_patients(
        self,
        *,
        patient_ids: list[str],
        condition: str,
    ) -> list[str]:
        """Find patient IDs from ``ai_patient_memory`` whose facts mention the condition.

        Looks for documents where:
          - ``patient_id`` ∈ provided list
          - ``category == 'condition'``
          - ``key`` matches the condition string (case-insensitive regex)
                OR ``value`` matches the condition string

        Returns deduped patient_id list. Best-effort: failures are logged
        and treated as 'no matches' to keep semantic fallback in play.
        """
        try:
            collection = self.mongo_store.get_collection("ai_patient_memory")
        except Exception as exc:  # pragma: no cover
            logger.warning("ai_patient_memory not available: %s", exc)
            return []

        # Build a case-insensitive regex for synonyms.
        synonyms = _condition_synonyms(condition)
        regex_alt = "|".join(synonyms)

        query = {
            "patient_id": {"$in": patient_ids},
            "category": "condition",
            "$or": [
                {"key": {"$regex": regex_alt, "$options": "i"}},
                {"value": {"$regex": regex_alt, "$options": "i"}},
            ],
        }

        ids: set[str] = set()
        try:
            cursor = collection.find(query, projection={"patient_id": 1})
            async for doc in cursor:
                pid = doc.get("patient_id")
                if pid:
                    ids.add(str(pid))
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("ai_patient_memory query failed: %s", exc)
            return []

        return sorted(ids)


# ── Synonym expansion ────────────────────────────────────────────────────────


# Canonical condition name → search synonyms.
# Used by both the structured-tag lookup and the data-signature lookup, so
# changes here propagate everywhere.
_CONDITION_SYNONYMS: dict[str, list[str]] = {
    "piles": ["piles", "hemorrhoid", "haemorrhoid"],
    "hemorrhoids": ["piles", "hemorrhoid", "haemorrhoid"],
    "diabetes": ["diabetes", "t1d", "t2d", "diabetic", "type 1 diabetes", "type 2 diabetes"],
    "hypertension": ["hypertension", "high blood pressure", "htn"],
    "obesity": ["obesity", "obese", "overweight"],
    "pcos": ["pcos", "polycystic ovary"],
    "asthma": ["asthma", "asthmatic"],
    "thyroid": ["thyroid", "hypothyroid", "hyperthyroid"],
}


# Canonical condition name → Qdrant data types whose existence strongly implies
# the condition. A patient with at least one record of any listed data type
# (in the last 180 days) is treated as a candidate cohort member.
#
# This is the heuristic that lets a query like "find my diabetes patients"
# work even when no patient has an explicit `diabetes` condition tag — the
# presence of CGM data / hypo events / SMBG readings is itself the signal.
#
# Only conditions with a clear data signal are listed. For conditions like
# piles where the only signal is free-text in notes, the semantic-search
# fallback in find_cohort still handles them — we just don't have a clean
# structured signature to add here.
_CONDITION_DATA_SIGNATURES: dict[str, list[str]] = {
    "diabetes": [
        "cgm_summary_stats",      # any CGM aggregate → patient wears a CGM
        "cgm_range_stats",
        "hyper_event",            # high-glucose events
        "hypo_event",             # low-glucose events
        "rapid_spike_event",
        "rapid_drop_event",
        "smbg",                   # self-monitored blood glucose readings
    ],
    # Hypertension / obesity would need vital-payload subtype filtering
    # (e.g. vital where measurement_type=blood_pressure) which the current
    # filter helpers can't express cleanly. Left empty for now; the tag +
    # semantic search paths still cover them.
    "hypertension": [],
    "obesity": [],
}


def _normalize_condition(condition: str) -> str:
    """Lowercase + strip; map common aliases to canonical keys.

    "Type 2 Diabetes" → "diabetes"
    "Hemorrhoids"     → "piles"
    "T1D"             → "diabetes"
    """
    raw = condition.strip().lower()
    # Inverted from _CONDITION_SYNONYMS so a synonym added there
    # normalizes here automatically — one table owns both directions.
    aliases = {
        syn: canonical
        for canonical, syns in _CONDITION_SYNONYMS.items()
        for syn in syns
        if syn != canonical and syn not in _CONDITION_SYNONYMS
    }
    return aliases.get(raw, raw)


def _condition_synonyms(condition: str) -> list[str]:
    """Expand a condition name into search synonyms.

    Used by the structured-tag lookup to match against ``key`` and ``value``
    fields in ``ai_patient_memory``. Unknown conditions fall back to the
    literal input string.
    """
    canonical = _normalize_condition(condition)
    return _CONDITION_SYNONYMS.get(canonical, [canonical])


__all__ = ["CohortTools"]
