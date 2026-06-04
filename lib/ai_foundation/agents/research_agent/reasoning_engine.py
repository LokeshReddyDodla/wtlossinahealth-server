"""
Research Agent reasoning engine.

Where ``health_query`` uses an open-ended thinker→tools→responder loop,
the research agent uses a structured pipeline:

    plan  →  execute  →  respond

Each stage is a single concrete operation. There are no multi-round
tool-call loops here — the planner already produced a complete spec,
so the executor knows exactly what to do. This keeps the pipeline fast
and auditable.

The reasoning engine also owns the responder LLM call — the final
narration of the result into a provider-friendly answer. The responder
sees the spec, the funnel, and the result — never the underlying records.
"""

from __future__ import annotations

import logging
from typing import Any

from lib.ai_foundation.models.gateway import ModelGateway
from lib.ai_foundation.models.registry import ModelTask

from .contracts import (
    CohortSpec,
    ExecutionResult,
    ExecutionResultKind,
)

logger = logging.getLogger(__name__)


# Inline responder system prompt. Mirror of prompts/responder.md.
_RESPONDER_SYSTEM_PROMPT = """You are the **Cohort Responder** for a clinical research agent.

You will receive:
1. The provider's original question
2. The structured `CohortSpec` the planner produced
3. The `ExecutionResult` the executor returned (counts, funnel, IDs, sample rows)

Your job: write a clear, concise, **clinically-grounded** answer for a care provider.

## Hard rules

1. **Do not invent numbers.** Only use values that appear in the ExecutionResult.
   If the result has `final_count: 8`, you may say "8 patients." Never say more or fewer.
2. **Always narrate the funnel when present.** Show the provider how each criterion narrowed the cohort. Format:
       - 412 patients in your panel
       - 47 had hypo events in the last 7 days
       - Of those, 12 also averaged under 6 hours of sleep
       - 8 patients match all criteria.
3. **Trust tags.** If `path == "scorecard"`, note "from precomputed scorecard."
   If `path == "qdrant_fallback"`, note "computed from raw records (slower paths)."
   If `path == "hybrid"`, note both sources.
4. **Listing patients:**
   - When the user explicitly asks ("show me", "who are they", "list them", "their names", "details"),
     use the `sample_rows` (each has `patient_id` and `name`) and list them by name.
     Format as a bulleted list: `- {name}` (one per line). Up to 25 names is fine.
   - When the question is a count/aggregate ("how many", "what %"), do NOT enumerate
     names — give the number and offer "want to see who they are?".
   - Never invent names or counts not present in `sample_rows`/`final_count`.
   - Patient UUIDs are debug context; only show them if the user explicitly asks for IDs.
5. **When `kind == not_implemented`**, explain plainly what isn't built yet,
   quote the `reason` field, and suggest the simpler thing the provider could ask instead.
6. **When the planner was a fallback** (heuristic), say so up front and ask for a rephrase.
7. **Conversation context.** When previous-turn messages are provided, treat references
   like "those patients", "the 17", "of those who…" as referring to the most recent
   cohort the prior turn established. If a referent is ambiguous, ask one clarifying question.

## Tone

You are talking to a clinician. Be brief, plain, and accurate.
Offer ONE concrete follow-up question at the end (e.g. "Want to see the matching patients?",
"Should I break this down by severity?"). One only — not a menu.

Length: 3-8 short lines unless the answer genuinely needs more.
"""


class ResearchReasoning:
    """Owns the responder LLM call.

    Kept separate from ``CohortExecutor`` so the executor stays pure (no LLM
    calls). Owns the responder model selection, prompt, and the small
    serialization shim that turns the ``ExecutionResult`` into a compact
    JSON-shaped payload the LLM can read.
    """

    def __init__(
        self,
        *,
        gateway: ModelGateway,
        responder_model_id: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._gateway = gateway
        self._responder_model_id = responder_model_id
        self._timeout = timeout_seconds

    async def respond(
        self,
        *,
        question: str,
        spec: CohortSpec,
        result: ExecutionResult,
        planner_meta: dict[str, Any] | None = None,
        history: list[Any] | None = None,
        trace_id: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Narrate the executor's result for the provider.

        Returns ``(answer_text, meta)`` where ``meta`` carries
        ``cost_usd``, ``latency_ms``, ``model_id``.

        ``history`` (if provided) is injected as chat messages between the
        system prompt and the current question payload, giving the LLM
        continuity across turns.
        """
        payload = _build_responder_payload(
            question=question,
            spec=spec,
            result=result,
            planner_meta=planner_meta or {},
        )
        messages: list[dict[str, str]] = [
            {"role": "system", "content": _RESPONDER_SYSTEM_PROMPT},
        ]
        for turn in (history or []):
            role = getattr(turn, "role", None) or (turn.get("role") if isinstance(turn, dict) else None)
            content = getattr(turn, "content", None) or (turn.get("content") if isinstance(turn, dict) else None)
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": str(content)})
        messages.append({"role": "user", "content": payload})
        llm = await self._gateway.complete(
            messages=messages,
            task=ModelTask.RESPONSE_GENERATION,
            model_id=self._responder_model_id,
            timeout=self._timeout,
            trace_id=trace_id,
        )
        return llm.content, {
            "model_id": llm.model_id,
            "cost_usd": llm.cost.total_usd if hasattr(llm, "cost") else 0.0,
            "latency_ms": llm.latency_ms,
            "trace_id": llm.trace_id,
        }


# ── Payload construction ─────────────────────────────────────────────────────


def _build_responder_payload(
    *,
    question: str,
    spec: CohortSpec,
    result: ExecutionResult,
    planner_meta: dict[str, Any],
) -> str:
    """Build the responder's user-message payload.

    Compact, JSON-shaped, no record contents. The LLM is reading a tiny
    summary regardless of cohort size — this is the whole reason the
    research agent scales.
    """
    fallback_note = ""
    if planner_meta.get("fallback"):
        fallback_note = (
            "\n\nNOTE: The structured planner failed and a heuristic fallback was used "
            f"(reason: {planner_meta.get('fallback_reason', 'unknown')}). "
            "Tell the provider you couldn't parse the question and ask them to rephrase."
        )

    funnel_lines = "\n".join(
        f"  - {step.step}: {step.count}" for step in (result.funnel or [])
    ) or "  (no funnel — single-step query)"

    sample_lines = ""
    if result.sample_rows:
        # Show up to 25 — matches the tools' name_enrich_limit. Format as
        # name first so the LLM doesn't accidentally surface UUIDs.
        formatted: list[str] = []
        for row in result.sample_rows[:25]:
            if isinstance(row, dict):
                name = row.get("name") or row.get("patient_id", "?")
                pid = row.get("patient_id", "")
                formatted.append(f"  - {name}  (id={pid})")
            else:
                formatted.append(f"  - {row}")
        sample_lines = (
            f"\nCohort members ({len(result.sample_rows)} shown"
            f"{f' of {result.final_count}' if result.final_count > len(result.sample_rows) else ''}):\n"
            + "\n".join(formatted)
        )

    aggregate_line = ""
    if result.aggregate_value is not None:
        aggregate_line = f"\nAggregate value: {result.aggregate_value}"

    not_impl_block = ""
    if result.kind == ExecutionResultKind.NOT_IMPLEMENTED:
        not_impl_block = (
            "\n\n!! EXECUTION NOT YET AVAILABLE !!\n"
            f"Reason: {result.reason}\n"
            "Explain this honestly to the provider and suggest a simpler question."
        )

    job_block = ""
    if result.kind == ExecutionResultKind.JOB_CREATED:
        job_block = (
            f"\n\nA background job was started: {result.job_id} (ETA: {result.eta}). "
            "Tell the provider it will run async and they'll be notified."
        )

    return (
        f"Provider's question:\n{question}\n\n"
        f"Planner spec:\n"
        f"  intent: {spec.intent.value}\n"
        f"  criteria: {[c.model_dump() for c in spec.criteria]}\n"
        f"  combinator: {spec.combinator.value}\n"
        f"  output: {spec.output.value}\n"
        f"  metric: {spec.metric}\n"
        f"  condition: {spec.condition}\n"
        f"  k: {spec.k}\n"
        f"  followup_hint: {spec.followup_hint}\n\n"
        f"Execution result:\n"
        f"  kind: {result.kind.value}\n"
        f"  path: {result.path}\n"
        f"  final_count: {result.final_count}\n"
        f"  final_ids (count only): {len(result.final_ids)}\n"
        f"Funnel:\n{funnel_lines}"
        f"{aggregate_line}"
        f"{sample_lines}"
        f"{not_impl_block}"
        f"{job_block}"
        f"{fallback_note}"
    )


__all__ = ["ResearchReasoning"]
