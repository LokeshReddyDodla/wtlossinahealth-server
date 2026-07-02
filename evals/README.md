# AI Foundation Evals

Golden-query regression suite for the Health Query Agent. Runs the **real
agent** (real LLMs, real prompts, real reasoning loop) against **fixture
data** (deterministic, timezone-correct, regenerated relative to "today"),
then scores every response two ways:

1. **Deterministic checks** (`checks.py`) — must_mention / must_not_mention /
   max_words. No LLM, no flakiness.
2. **LLM judge** (`judge.py`) — accuracy, safety, completeness, tone (1-5)
   plus a fabricated-claims list, via the registry's `QUALITY_JUDGE` route.
   Fabrication = ungrounded claims about *the patient's data*; general
   medical knowledge and fixture-derived arithmetic are explicitly not
   fabrication.

## Running

```bash
.venv/bin/python -m evals.run                 # full suite (~$0.7, ~2 min)
.venv/bin/python -m evals.run --case med_stop # one case
.venv/bin/python -m evals.run --no-judge      # deterministic checks only
.venv/bin/python -m evals.run --list          # list cases
```

Exit code 0 = gate passed. Gate fails when any `critical: true` case fails
or the overall pass rate drops below 85%. Reports land in `evals/reports/`
(gitignored); judge scores are also pushed to Langfuse against each case's
trace as `eval_accuracy` / `eval_safety` / `eval_completeness` / `eval_tone`.

**Run this before shipping any prompt or model-routing change.**

## Anatomy

| File | Purpose |
|---|---|
| `golden/health_query.yaml` | The cases: query, checks, judge criteria, critical flag |
| `fixtures.py` | Ground-truth patient data + fakes (retriever/memory/resolver) |
| `agent_factory.py` | Assembles the agent: real gateway+prompts+engine, fake data layer |
| `checks.py` | Deterministic assertions |
| `judge.py` | LLM judge with calibrated fabrication definition |
| `run.py` | CLI runner, concurrency 3, JSON reports, gate |

## Adding a case

Append to `golden/health_query.yaml`. Ground every expected number in
`fixtures.py::default_records()` — the judge receives the complete fixture
as ground truth, so anything the response claims about the patient that
isn't there counts as fabrication. Mark safety/honesty cases
`critical: true` so one failure fails the run.

## What it has already caught

First runs of this suite found (all fixed):
- `_ensure_prompts` truthiness bug — empty PromptRegistry is falsy, skipping registration
- Coordinator + engine non-stream responder calls missing timeouts → 15s spec
  default failed whole multi-domain queries (no fallback with explicit model_id)
- Active-hypo queries dead-ending in the clarification path with truncated text
- No hypoglycemia first-aid guidance in the patient system prompt
- Unhedged causal claims ("your walking is definitely why...")

## Notes

- Prompts are Langfuse-first in production. Local `.md` edits only take
  effect where Langfuse has no copy of that prompt (or locally) — sync
  prompt changes to Langfuse when deploying.
- Judge variance exists; the calibrated fabrication definition keeps it
  low, but a borderline tone case may flip occasionally. Critical cases
  are phrased to be unambiguous.
