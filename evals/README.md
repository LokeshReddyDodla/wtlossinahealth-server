# AI Foundation Evals

Golden-query regression suites for every AI surface. Each suite runs the
**real agent** (real LLMs, real prompts, real pipeline) against **fixture
data** (deterministic, timezone-correct, regenerated relative to "today"),
then scores every response two ways:

1. **Deterministic checks** (`checks.py`) — must_mention / must_not_mention /
   max_words. No LLM, no flakiness.
2. **LLM judge** (`judge.py`) — accuracy, safety, completeness, tone (1-5)
   plus a fabricated-claims list, via the registry's `QUALITY_JUDGE` route.
   Fabrication = ungrounded claims about *the patient's data*; general
   medical knowledge and fixture-derived arithmetic are explicitly not
   fabrication.

## Suites

| Suite | Target | Cases | What it protects |
|---|---|---|---|
| `golden/health_query.yaml` | chat agent | 15 | grounding, fabrication traps, med/emergency safety, memory, tone |
| `golden/proactive_monitor.yaml` | monitor | 4 | no false alarms (notification fatigue), hypo detection, severity |
| `golden/voice_mode.yaml` | chat agent (voice) | 3 | no markdown in spoken output, speakable length, voice safety |
| `golden/meal_analysis.yaml` | meal pipeline | 4 | extraction accuracy, scoring calibration, vague-input hedging |

## Running

```bash
.venv/bin/python -m evals.run                                        # health query (~$0.7)
.venv/bin/python -m evals.run --suite evals/golden/proactive_monitor.yaml
.venv/bin/python -m evals.run --case med_stop                        # one case
.venv/bin/python -m evals.run --no-judge                             # deterministic only
.venv/bin/python -m evals.run --list                                 # list cases
.venv/bin/python -m evals.mine_feedback --days 30                    # thumbs-down → draft cases
```

## Model bake-offs

```bash
# Which responder writes the best patient answers? (full suite each)
.venv/bin/python -m evals.bakeoff --vary AI_REASONING_RESPONDER_MODEL \
    --models claude-sonnet-4-6,gpt-5.1,gemini-2.5-pro

# Quick read on a cheaper thinker (3 cases)
.venv/bin/python -m evals.bakeoff --vary AI_REASONING_THINKER_MODEL \
    --models claude-haiku-4-5-20251001,gpt-4.1-mini --case med_stop --case glucose_yesterday
```

Side-by-side pass rate, judge scores, cost, and latency per candidate.
**When a new model generation ships**: register it in `models/registry.py`,
bake it off against the incumbent, promote on data. Every scored response
(evals + production feedback) also accumulates in Langfuse — that's the
future fine-tuning/distillation dataset if we ever want to train a cheaper
model on the best model's answers.

CI: `.github/workflows/evals.yml` runs all four suites on PRs touching
prompts / model routing / agents / evals, plus nightly at 03:30 IST to
catch provider-side model drift. Needs `EVAL_ANTHROPIC_API_KEY`,
`EVAL_OPENAI_API_KEY`, `EVAL_GOOGLE_API_KEY` repo secrets (skips with a
warning if unset).

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
| `run.py` | CLI runner, concurrency 3, majority-vote judge, retry-once w/ flaky reporting, JSON reports, gate |
| `bakeoff.py` | Same suite across candidate models — routing decisions on data |
| `mine_feedback.py` | Thumbs-down Langfuse traces → draft golden cases |

## Adding a case

Append to the right `golden/*.yaml`. Ground every expected number in the
suite's fixture module — the judge receives the complete fixture as ground
truth. Mark safety/honesty cases `critical: true` so one failure fails the
run. `relaxed_judge: true` limits the judge gate to safety + fabrications
for estimation cases whose real gate is the deterministic bounds.

**Growth rule**: a new case must come from (1) a real user failure (run
`mine_feedback`), (2) a new feature, or (3) an unprobed failure CLASS —
never "more cases" for its own sake.

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
