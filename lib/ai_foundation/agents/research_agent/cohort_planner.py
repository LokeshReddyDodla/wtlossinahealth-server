"""
Cohort Planner — question → CohortSpec.

Single structured-extraction LLM call that turns the provider's free-text
research question into a ``CohortSpec`` the executor can run deterministically.

Why structured: cohort questions have predictable shape (aggregate / match /
intersect / rank / find / research). Locking that shape into a pydantic
model up-front makes the executor a pure dispatch table and makes the
whole pipeline auditable — the spec is logged, the funnel is logged, the
final answer is logged.

The planner uses the gateway's ``extract()`` with ``ModelTask.INTENT_EXTRACTION``,
so it routes to the same cheap "thinker" model the rest of the foundation
uses. Failures fall back to a heuristic spec (best-effort) so that even if
the LLM hiccups the agent still returns something useful.
"""

from __future__ import annotations

import logging
from typing import Any

from lib.ai_foundation.models.gateway import ModelGateway
from lib.ai_foundation.models.registry import ModelTask

from .contracts import (
    CohortCombinator,
    CohortIntent,
    CohortOutput,
    CohortSpec,
)

logger = logging.getLogger(__name__)


# ── Inline system prompt (canonical) ─────────────────────────────────────────
#
# Kept inline rather than read from the prompt registry so the planner is
# self-contained and robust to registry init failures. A markdown copy
# lives in ``prompts/planner.md`` for design-time reference and for future
# Langfuse-managed iteration.

from lib.ai_foundation.agents.health_query.contracts import HealthDataType

# Rendered below with the full HealthDataType enum — the planner's hard rule
# "NEVER invent a data_type not in the list" makes ANY omission here a
# provider-facing capability gap.
_PLANNER_SYSTEM_PROMPT_TEMPLATE = """You are the **Cohort Planner** for a clinical research agent that helps care providers analyze patient cohorts (groups of 10 to 1000+ patients).

Your only job is to parse the provider's question into a structured `CohortSpec`. You do NOT answer the question — you produce the plan that another part of the system will execute.

## What you are choosing

For every question, pick one `intent`:

- `aggregate` — counts, averages, distributions across the cohort.
  Examples: "How many had hypo?", "What % are off target?", "Average sleep last week"
- `match` — patients matching ONE criterion. Returns IDs.
  Examples: "Who had a hypo event this week?"
- `match_and_count` — patients matching TWO OR MORE criteria with AND/OR/NOT.
  Examples: "Who has hypo AND poor sleep AND low protein?"
- `rank` — top-K patients by some criterion.
  Examples: "My most at-risk patients", "Top 20 by rising A1C"
- `find` — identify patients with a named condition / disease.
  Examples: "My piles patients", "Patients with diabetes"
- `research` — deep per-patient analysis across the cohort.
  Examples: "Research what issues my piles patients face", "Generate weekly reviews for all"

## How to fill the rest of the spec

- `criteria` — one `Criterion` per filter the question mentions. Each has:
    - `data_type` — must be one of the known Qdrant data types:
        {data_types}
    - `filter` — numeric filter as `{key: {"lt": N}}` / `{"gt": N}` / `{"lte": N}` / `{"gte": N}`
                or scalar equality as `{key: value}`
    - `window` — "1d", "3d", "7d", "14d", "30d", "60d", "90d", "180d", "1y", "365d", "all" (default "7d")
        - "last year" / "in the past year" / "this year" → "1y"
        - "last 6 months" / "in the past 6 months" → "180d"
    - `label` — short human phrase like "hypo last 7d" or "sleep <6h last 7d"

- `combinator` — AND / OR / NOT. Default AND. NOT means "exclude patients matching this criterion."

- `output`:
    - `count`  — for aggregate intent
    - `ids`    — for match intent
    - `ids_with_funnel` — for match_and_count intent (almost always)
    - `top_k`  — for rank intent
    - `extraction` — for research intent

- `k` — required when intent is `rank`. Default 20 if not stated.
- `metric` — required when intent is `aggregate`. Use:
    - `count_unique_patients` (default for "how many patients")
    - `count_records` (for "how many events / entries")
    - `facet:<field>` (for "break it down by …")
- `condition` — required when intent is `find`. The literal disease/condition word(s).
- `followup_hint` — if the user adds "and tell me about the top 3" or similar, capture it here.

## Hard rules

1. NEVER invent a data_type that isn't in the list above. If unsure, pick the closest one and add it to `label`.
2. NEVER set a window longer than "90d" unless the user explicitly said so. When the user says "last year" / "this year" / "in 2026" → use `"1y"`. When the user says "last 6 months" → use `"180d"`. When the user says "ever" / "all time" / "historically" → use `"all"`.
3. If the question is ambiguous between aggregate and match (e.g. "hypo patients" — count? list?), prefer `match_and_count` with `ids_with_funnel` — it's more useful.
4. If the user mentions a condition by name and ALSO criteria (e.g. "piles patients with severe symptoms"), the planner emits intent=`match_and_count` with `condition` set; the executor will resolve the cohort via find_cohort first, then intersect.
5. Keep `criteria` minimal — don't add filters the user didn't ask for.

## Follow-up rules (when prior conversation turns are in the context)

These are the MOST IMPORTANT rules — read carefully.

When the user uses references like "those", "of those", "those patients",
"this group", "the same group", "of them", "in that cohort", they are
referring to the cohort that the most recent prior turn established. You
must reconstruct that cohort and carry it into the new spec:

- If the prior turn was a `find` (e.g. "find my diabetes patients"), set
  `condition` to whatever condition the prior turn used. The executor
  will narrow by that condition before applying any new criteria.
- If the prior turn established a cohort via criteria (e.g. "patients with hypo
  events this week"), include the same criteria (or a clear equivalent) in
  the new spec as the first criterion, alongside any new criteria the user added.
- If the prior turn was a `find` for condition X and the new question
  adds a new filter Y (e.g. Turn 1 = "find diabetes patients", Turn 2 = "of
  those, how many sleep <6h"), emit:
    intent: match_and_count
    condition: "diabetes"
    criteria: [Criterion(data_type=sleep, filter={hours: {lt: 6}}, window=7d)]
    output: count or ids_with_funnel
- If the reference is ambiguous (no clear prior cohort), set intent=match
  with the new criterion only and add followup_hint="ambiguous_reference".

Do NOT just answer for the whole panel and pretend it was scoped — that
gives wrong numbers.

## Negation rules

Phrases that mean "find patients who DO NOT match":
  "have not", "haven't", "without", "missing", "no", "lack", "don't have",
  "weren't", "didn't", "never", "absent", "no record of", "no entries of"

For a single negated criterion like "patients who have NOT logged any meals
in the last 30 days", emit:
  intent: match_and_count
  combinator: NOT
  criteria: [Criterion(data_type=meal, filter={}, window=30d, label="any meal last 30d")]
  output: ids_with_funnel

The executor will compute (cohort − matched), which gives the correct
"who DOES NOT have this" answer. NEVER emit a positive `match` intent and
hope the responder will invert it — the responder cannot invert tool
results, it can only narrate them.

## "What's common" rules

When the user asks "what conditions exist in the panel", "what are the
most common issues", "summarize the health profile of my patients",
"give me a breakdown by condition", emit:
  intent: aggregate
  metric: condition_distribution
  output: count
  criteria: []      # ← no per-data-type filter, the executor will iterate
                     # all known condition signatures and return counts.

You will be given the user's question. Respond by populating the `CohortSpec` schema.
"""

# .replace, not .format — the template is full of literal JSON braces.
_PLANNER_SYSTEM_PROMPT = _PLANNER_SYSTEM_PROMPT_TEMPLATE.replace(
    "{data_types}", ", ".join(dt.value for dt in HealthDataType),
)


class CohortPlanner:
    """LLM-backed parser from research question to ``CohortSpec``."""

    def __init__(
        self,
        *,
        gateway: ModelGateway,
        model_id: str | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._gateway = gateway
        self._model_id = model_id  # If None, gateway routes by task.
        self._timeout = timeout_seconds

    async def plan(
        self,
        *,
        question: str,
        cohort_size_hint: int | None = None,
        history: list[Any] | None = None,
        trace_id: str | None = None,
    ) -> tuple[CohortSpec, dict[str, Any]]:
        """Turn ``question`` into a ``CohortSpec``.

        ``history`` is an optional list of prior ``HistoryTurn``-shaped
        items (or dicts with ``role`` and ``content``). When present, the
        planner sees them as ordinary chat messages before the current
        question, which lets it resolve references like "those patients"
        or "the 17" without the caller having to rephrase the whole context.

        Returns ``(spec, meta)`` where ``meta`` carries ``model_id``,
        ``cost_usd``, ``latency_ms`` for the calling agent's telemetry.
        On LLM failure, returns a heuristic fallback spec with
        ``meta["fallback"] = True`` so the responder can warn the user.
        """
        user_msg = question.strip()
        if cohort_size_hint is not None:
            user_msg += f"\n\n(Cohort size: {cohort_size_hint} patients.)"

        messages: list[dict[str, str]] = [
            {"role": "system", "content": _PLANNER_SYSTEM_PROMPT},
        ]
        for turn in (history or []):
            role = getattr(turn, "role", None) or (turn.get("role") if isinstance(turn, dict) else None)
            content = getattr(turn, "content", None) or (turn.get("content") if isinstance(turn, dict) else None)
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": str(content)})
        messages.append({"role": "user", "content": user_msg})

        try:
            spec, llm_meta = await self._gateway.extract(
                messages=messages,
                response_model=CohortSpec,
                task=ModelTask.INTENT_EXTRACTION,
                model_id=self._model_id,
                timeout=self._timeout,
                trace_id=trace_id,
            )
            # Defensive: gpt-5.1 sometimes drops NOT despite the prompt. If the
            # question clearly negates and there is exactly one criterion with
            # combinator AND, flip to NOT so the executor computes
            # (cohort − matched). Without this, "patients who have NOT logged X"
            # silently becomes "patients who HAVE logged X."
            spec = _force_not_combinator_if_negated(spec, question)
            return spec, {
                "model_id": llm_meta.model_id,
                "cost_usd": llm_meta.cost.total_usd if hasattr(llm_meta, "cost") else 0.0,
                "latency_ms": llm_meta.latency_ms,
                "trace_id": llm_meta.trace_id,
                "fallback": False,
            }
        except Exception as exc:  # noqa: BLE001 — bound by fallback below
            logger.warning("CohortPlanner.extract failed (%s); using heuristic fallback", exc)
            return _heuristic_spec(question), {
                "model_id": "heuristic",
                "cost_usd": 0.0,
                "latency_ms": 0,
                "trace_id": trace_id,
                "fallback": True,
                "fallback_reason": str(exc),
            }


# ── Heuristic fallback ───────────────────────────────────────────────────────


# Words / phrases that signal the user is asking for *absence* of something.
# Order matters slightly — multi-word phrases come first so we match them
# before the single-word "no" / "not" which can false-positive easily.
_NEGATION_PHRASES = (
    "have not logged",
    "haven't logged",
    "have not had",
    "haven't had",
    "have not recorded",
    "haven't recorded",
    "have no record",
    "without any",
    "without logging",
    "without a",
    "did not log",
    "didn't log",
    "do not have",
    "don't have",
    "no record of",
    "no entries of",
    "missing",
    "haven't",
    " have not ",
    " has not ",
    " hasn't ",
    " not yet ",
    " never ",
)


def _question_is_negated(question: str) -> bool:
    """True if the question is asking 'who DOES NOT have/log X'.

    Conservative on purpose — false positives flip semantics, so we look for
    explicit negation phrases rather than every appearance of 'not'.
    """
    q = f" {question.lower().strip()} "
    return any(phrase in q for phrase in _NEGATION_PHRASES)


def _force_not_combinator_if_negated(
    spec: CohortSpec,
    question: str,
) -> CohortSpec:
    """Override planner-emitted combinator to NOT when the question is
    clearly negated and the planner dropped it.

    Only fires when ALL of:
      - The question contains an explicit negation phrase
      - The spec has exactly one criterion
      - The current combinator is AND (the planner's default)
      - The intent is match or match_and_count (combinator only meaningful there)

    Without this, follow-up bugs like "patients who have NOT logged meals
    in 30 days" silently return the population WITH meals instead.
    """
    if spec.combinator != CohortCombinator.AND:
        return spec
    if spec.intent not in (CohortIntent.MATCH, CohortIntent.MATCH_AND_COUNT):
        return spec
    if len(spec.criteria) != 1:
        return spec
    if not _question_is_negated(question):
        return spec
    logger.info(
        "CohortPlanner: forcing combinator=NOT on negated question (planner emitted AND)"
    )
    spec.combinator = CohortCombinator.NOT
    # match alone doesn't carry funnel; bump to match_and_count so the
    # executor reports the funnel reduction.
    if spec.intent == CohortIntent.MATCH:
        spec.intent = CohortIntent.MATCH_AND_COUNT
        if spec.output == CohortOutput.IDS:
            spec.output = CohortOutput.IDS_WITH_FUNNEL
    return spec


def _heuristic_spec(question: str) -> CohortSpec:
    """Best-effort spec when the LLM call fails.

    The heuristic is intentionally conservative: it always emits an
    ``aggregate`` intent that just counts the cohort, so the responder can
    say "the planner failed — here is the raw cohort size; please rephrase."
    """
    return CohortSpec(
        intent=CohortIntent.AGGREGATE,
        criteria=[],
        combinator=CohortCombinator.AND,
        output=CohortOutput.COUNT,
        metric="count_unique_patients",
        followup_hint="planner_fallback",
    )


__all__ = ["CohortPlanner"]
