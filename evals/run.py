"""Eval runner — golden queries through the real agent, scored two ways.

    .venv/bin/python -m evals.run                 # full suite + judge
    .venv/bin/python -m evals.run --case med_stop # one case
    .venv/bin/python -m evals.run --no-judge      # deterministic checks only
    .venv/bin/python -m evals.run --list          # list cases, run nothing

Exit code 0 = gate passed. 1 = a critical case failed or pass rate < 85%.
Reports land in evals/reports/<timestamp>.json; judge scores are also
pushed to Langfuse against each case's trace (when Langfuse is enabled).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

_SUITE_DEFAULT = Path(__file__).parent / "golden" / "health_query.yaml"
_REPORTS_DIR = Path(__file__).parent / "reports"

PASS_RATE_GATE = 0.85
CONCURRENCY = 3


def _load_suite(path: Path) -> tuple[str, list[dict[str, Any]]]:
    with open(path, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    return doc.get("target", "health_query"), doc["cases"]


async def _run_case(case: dict[str, Any], *, no_judge: bool) -> dict[str, Any]:
    from lib.ai_foundation.agents.state import AgentContext, AgentInput

    from .agent_factory import build_eval_agent, shared_gateway
    from .checks import run_checks
    from .fixtures import (
        EVAL_PATIENT_ID,
        EVAL_TIMEZONE,
        default_facts,
        default_records,
        weight_loss_facts,
        weight_loss_records,
    )
    from .judge import judge_case_voted

    fixture = case.get("fixture", "default")
    if fixture == "weight_loss":
        records, facts, name = weight_loss_records(), weight_loss_facts(), "Rohan"
    elif fixture == "default":
        records, facts, name = default_records(), default_facts(), None
    else:  # "empty"
        records, facts, name = [], [], None
    agent = build_eval_agent(records, facts, patient_name=name)

    local_time = datetime.now(ZoneInfo(EVAL_TIMEZONE)).strftime("%Y-%m-%d %H:%M (%A)")
    agent_input = AgentInput(
        message=case["query"],
        context=AgentContext(
            patient_id=EVAL_PATIENT_ID,
            user_id=EVAL_PATIENT_ID,
            user_role="patient",
            thread_id=f"eval:{case['id']}",
            patient_ids=[EVAL_PATIENT_ID],
            # Case-level metadata (e.g. output_mode: voice) merges in
            metadata={"local_time": local_time, **(case.get("metadata") or {})},
        ),
    )

    start = time.perf_counter()
    try:
        output = await agent.run(agent_input)
        response = output.message or ""
        cost = output.cost_usd or 0.0
        trace_id = output.trace_id
        error = None
    except Exception as exc:  # an agent crash is itself an eval failure
        response, cost, trace_id, error = "", 0.0, None, f"{type(exc).__name__}: {exc}"
    latency_ms = int((time.perf_counter() - start) * 1000)

    check_result = run_checks(response, case.get("checks") or {})

    judgment = None
    if not no_judge and response and not error:
        try:
            judgment = await judge_case_voted(
                shared_gateway(),
                question=case["query"],
                response=response,
                fixture_texts=[r["text_repr"] for r in records],
                facts=[f"{f.key}: {f.value}" for f in facts]
                + [f"patient's current local time (known to the assistant): {local_time}"],
                criteria=case.get("criteria", ""),
            )
        except Exception as exc:
            error = f"judge failed: {exc}"

    passed = (
        error is None
        and check_result.passed
        and (no_judge or _judge_ok(judgment, case))
    )

    # Push judge scores to Langfuse against the agent's trace
    if judgment and trace_id:
        gw = shared_gateway()
        for name in ("accuracy", "safety", "completeness", "tone"):
            try:
                gw.log_score(
                    trace_id=trace_id,
                    name=f"eval_{name}",
                    value=float(getattr(judgment, name)),
                    comment=f"eval case {case['id']}",
                )
            except Exception:
                pass

    return {
        "id": case["id"],
        "category": case.get("category", ""),
        "critical": bool(case.get("critical", False)),
        "passed": passed,
        "latency_ms": latency_ms,
        "cost_usd": round(cost, 6),
        "trace_id": trace_id,
        "error": error,
        "check_failures": check_result.failures,
        "judge": judgment.model_dump() if judgment else None,
        "response": response,
    }


async def _run_monitor_case(case: dict[str, Any], *, no_judge: bool) -> dict[str, Any]:
    """Run a proactive-monitor scenario and score the produced insights."""
    from lib.ai_foundation.agents.proactive_monitor.agent import ProactiveMonitorAgent
    from lib.ai_foundation.agents.proactive_monitor.contracts import SEVERITY_RANK

    from .agent_factory import shared_gateway
    from .checks import run_checks
    from .fixtures import EVAL_PATIENT_ID, EVAL_PATIENT_NAME, FakeMemory, FixtureRetriever
    from .judge import judge_case_voted
    from .monitor_fixtures import SCENARIOS, pick_afternoon_timezone

    tz = pick_afternoon_timezone()
    records = SCENARIOS[case["scenario"]](tz)
    agent = ProactiveMonitorAgent(
        gateway=shared_gateway(),
        qdrant=FixtureRetriever(records, tz_name=tz),
        memory=FakeMemory(),
        insight_tracker=None,  # no dedup — every scenario judged fresh
    )

    patient_name = case.get("patient_name", EVAL_PATIENT_NAME)
    start = time.perf_counter()
    try:
        result = await agent.scan_patient(EVAL_PATIENT_ID, patient_name, tz)
        insights = result.insights
        error = None
    except Exception as exc:
        insights, error = [], f"{type(exc).__name__}: {exc}"
    latency_ms = int((time.perf_counter() - start) * 1000)

    combined = "\n".join(f"[{i.severity}] {i.title}: {i.body}" for i in insights)

    # Structural expectations (deterministic, monitor-specific)
    failures: list[str] = []
    checks = case.get("checks") or {}
    if "max_insights" in checks and len(insights) > checks["max_insights"]:
        failures.append(f"max_insights: got {len(insights)} > {checks['max_insights']}")
    if "min_insights" in checks and len(insights) < checks["min_insights"]:
        failures.append(f"min_insights: got {len(insights)} < {checks['min_insights']}")
    if insights and "max_severity" in checks:
        cap = SEVERITY_RANK[checks["max_severity"]]
        over = [i.title for i in insights if SEVERITY_RANK[i.severity] > cap]
        if over:
            failures.append(f"max_severity {checks['max_severity']} exceeded by: {over}")
    if "min_severity" in checks:
        floor = SEVERITY_RANK[checks["min_severity"]]
        if not any(SEVERITY_RANK[i.severity] >= floor for i in insights):
            failures.append(f"min_severity: no insight at/above {checks['min_severity']}")
    text_checks = {k: v for k, v in checks.items()
                   if k in ("must_mention", "must_not_mention", "max_words")}
    if combined or text_checks.get("must_mention"):
        cr = run_checks(combined, text_checks)
        # empty-response failure only matters when insights were required
        failures.extend(f for f in cr.failures
                        if f != "empty response" or checks.get("min_insights", 0) > 0)

    judgment = None
    if not no_judge and insights and not error:
        try:
            judgment = await judge_case_voted(
                shared_gateway(),
                question=(
                    "Proactive scan: should the patient be notified with these "
                    "insights, and are they grounded in the data?"
                ),
                response=combined,
                fixture_texts=[r["text_repr"] for r in records],
                facts=[],
                criteria=case.get("criteria", ""),
            )
        except Exception as exc:
            error = f"judge failed: {exc}"

    passed = (
        error is None
        and not failures
        and (no_judge or _judge_ok(judgment, case))
    )

    return {
        "id": case["id"],
        "category": case.get("category", ""),
        "critical": bool(case.get("critical", False)),
        "passed": passed,
        "latency_ms": latency_ms,
        "cost_usd": 0.0,  # ScanResult doesn't expose cost; Langfuse has it per trace
        "trace_id": getattr(result, "trace_id", None) if error is None else None,
        "error": error,
        "check_failures": failures,
        "judge": judgment.model_dump() if judgment else None,
        "response": combined,
    }


async def _run_meal_case(case: dict[str, Any], *, no_judge: bool) -> dict[str, Any]:
    """Run a meal description through the full preview pipeline and score it."""
    from lib.ai_foundation.agents.meal_analysis.contracts import (
        MealPreviewRequest,
        MealSlot,
        MealSource,
    )

    from .agent_factory import shared_gateway
    from .checks import run_checks
    from .fixtures import EVAL_PATIENT_ID, EVAL_TIMEZONE
    from .judge import judge_case_voted
    from .meal_fixtures import PERSONAS, build_meal_agent

    persona = case.get("persona", "t2d")
    agent = build_meal_agent(persona)
    slot = MealSlot(case.get("slot", "lunch"))
    # consumed_at aligned with the slot — otherwise every case triggers a
    # "lunch in the evening?" timing concern from the scorer.
    slot_hours = {"breakfast": 8, "lunch": 13, "dinner": 19, "snack": 16}
    consumed_at = datetime.now(ZoneInfo(EVAL_TIMEZONE)).replace(
        hour=slot_hours[slot.value], minute=30, second=0, microsecond=0,
    )
    request = MealPreviewRequest(
        slot=slot,
        source=MealSource.TEXT,
        text=case["query"],
        consumed_at=consumed_at,
    )

    start = time.perf_counter()
    result = None
    try:
        result = await agent.analyze(patient_id=EVAL_PATIENT_ID, request=request)
        error = None
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = int((time.perf_counter() - start) * 1000)

    failures: list[str] = []
    response = ""
    checks = case.get("checks") or {}

    if result is not None:
        ext = result.extraction
        items_txt = ", ".join(f"{i.name} ({i.portion}{i.unit})" for i in ext.items)
        pred = result.predicted_glucose
        response = (
            f"Meal: {ext.name}. Items: {items_txt}. "
            f"Extraction confidence: {ext.overall_confidence.value}. "
            f"Macros: {ext.total_macros.calories:.0f} kcal, "
            f"{ext.total_macros.carbs:.0f}g carbs, {ext.total_macros.protein:.0f}g protein. "
            f"Score: {result.score.overall}/100. "
            f"Concerns: {'; '.join(c.text for c in result.score.concerns) or 'none'}. "
            f"Positives: {'; '.join(p.text for p in result.score.positives) or 'none'}."
        )
        if pred:
            response += (
                f" Predicted glucose rise: {pred.range_mg_dl_low}-{pred.range_mg_dl_high} "
                f"mg/dL, peak ~{pred.peak_minutes_after} min ({pred.confidence})."
            )

        # Structural sanity — deterministic
        if not ext.items:
            failures.append("extraction produced no food items")
        if "carbs_between" in checks:
            lo, hi = checks["carbs_between"]
            if not (lo <= ext.total_macros.carbs <= hi):
                failures.append(f"carbs_between: {ext.total_macros.carbs:.0f}g not in [{lo}, {hi}]")
        if "score_between" in checks:
            lo, hi = checks["score_between"]
            if not (lo <= result.score.overall <= hi):
                failures.append(f"score_between: {result.score.overall} not in [{lo}, {hi}]")
        if pred:
            if not (pred.range_mg_dl_low < pred.range_mg_dl_high):
                failures.append(f"prediction range inverted: {pred.range_mg_dl_low}-{pred.range_mg_dl_high}")
            if not (10 <= pred.peak_minutes_after <= 300):
                failures.append(f"peak_minutes_after implausible: {pred.peak_minutes_after}")
        text_checks = {k: v for k, v in checks.items()
                       if k in ("must_mention", "must_not_mention", "max_words")}
        failures.extend(run_checks(response, text_checks).failures)

    judgment = None
    if not no_judge and response and not error:
        try:
            judgment = await judge_case_voted(
                shared_gateway(),
                question=f"Meal analysis for the description: {case['query']!r}",
                response=response,
                fixture_texts=[f"Patient's meal description: {case['query']}"],
                facts=PERSONAS[persona]["judge_facts"],
                criteria=case.get("criteria", ""),
                mode="estimation",
            )
        except Exception as exc:
            error = f"judge failed: {exc}"

    passed = (
        error is None
        and not failures
        and (no_judge or _judge_ok(judgment, case))
    )

    return {
        "id": case["id"],
        "category": case.get("category", ""),
        "critical": bool(case.get("critical", False)),
        "passed": passed,
        "latency_ms": latency_ms,
        "cost_usd": 0.0,  # cost lives in Langfuse per trace
        "trace_id": result.model_trace_id if result else None,
        "error": error,
        "check_failures": failures,
        "judge": judgment.model_dump() if judgment else None,
        "response": response,
    }


def _judge_ok(judgment, case: dict[str, Any]) -> bool:
    """Judge pass bar. `relaxed_judge: true` cases pass on safety + no
    real fabrication alone — for estimation cases whose real gate is the
    deterministic bounds, where judge accuracy scores are noisy nitpicks."""
    if judgment is None:
        return True
    if case.get("relaxed_judge"):
        real_fabrication = bool(judgment.fabricated_claims) and judgment.accuracy <= 3
        return judgment.safety >= 4 and not real_fabrication
    return judgment.passed


_EXECUTORS = {
    "health_query": _run_case,
    "proactive_monitor": _run_monitor_case,
    "meal_analysis": _run_meal_case,
}


async def _run_suite(
    cases: list[dict[str, Any]], *, target: str, no_judge: bool,
) -> list[dict[str, Any]]:
    executor = _EXECUTORS[target]
    sem = asyncio.Semaphore(CONCURRENCY)

    async def bounded(case: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            result = await executor(case, no_judge=no_judge)
            result["flaky"] = False
            # One retry on failure: the agent samples a fresh response each
            # run, so a single bad sample shouldn't fail the gate. A case
            # that passes on retry is reported as FLAKY (visible, counted),
            # a case that fails twice is a real failure.
            if not result["passed"]:
                retry = await executor(case, no_judge=no_judge)
                if retry["passed"]:
                    retry["flaky"] = True
                    retry["first_attempt_failures"] = (
                        result["check_failures"]
                        or (result["judge"] or {}).get("fabricated_claims")
                        or [result["error"] or "judge below threshold"]
                    )
                    result = retry
                else:
                    result["flaky"] = False
            marker = "PASS (flaky)" if result["flaky"] else (
                "PASS" if result["passed"] else "FAIL"
            )
            crit = " [CRITICAL]" if result["critical"] and not result["passed"] else ""
            print(f"  {marker}{crit}  {result['id']:<22} "
                  f"{result['latency_ms']:>6}ms  ${result['cost_usd']:.4f}")
            return result

    return await asyncio.gather(*(bounded(c) for c in cases))


def main() -> int:
    # LiteLLM reads provider keys from os.environ; load .env for local runs.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    parser = argparse.ArgumentParser(description="Run the AI Foundation eval suite.")
    parser.add_argument("--suite", type=Path, default=_SUITE_DEFAULT)
    parser.add_argument("--case", action="append", help="Run only these case IDs (repeatable).")
    parser.add_argument("--no-judge", action="store_true", help="Deterministic checks only.")
    parser.add_argument("--list", action="store_true", help="List cases without running.")
    args = parser.parse_args()

    target, cases = _load_suite(args.suite)
    if args.case:
        cases = [c for c in cases if c["id"] in set(args.case)]
        if not cases:
            print(f"No cases match {args.case}", file=sys.stderr)
            return 2

    if args.list:
        for c in cases:
            crit = " [critical]" if c.get("critical") else ""
            desc = c.get("query") or c.get("scenario", "")
            print(f"  {c['id']:<22} {c.get('category', ''):<14}{crit}  {desc[:60]}")
        return 0

    print(f"Running {len(cases)} eval cases "
          f"(target={target}, judge={'off' if args.no_judge else 'on'})...")
    results = asyncio.run(_run_suite(cases, target=target, no_judge=args.no_judge))

    passed = [r for r in results if r["passed"]]
    critical_failures = [r for r in results if r["critical"] and not r["passed"]]
    pass_rate = len(passed) / len(results) if results else 0.0
    total_cost = sum(r["cost_usd"] for r in results)

    _REPORTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = _REPORTS_DIR / f"eval_{stamp}.json"
    flaky = [r for r in results if r.get("flaky")]
    report = {
        "timestamp": stamp,
        "suite": str(args.suite),
        "pass_rate": round(pass_rate, 3),
        "total_cost_usd": round(total_cost, 4),
        "critical_failures": [r["id"] for r in critical_failures],
        "flaky_cases": [r["id"] for r in flaky],
        "results": results,
    }
    report_path.write_text(json.dumps(report, indent=2, default=str))

    print(f"\n{'=' * 60}")
    print(f"Pass rate: {len(passed)}/{len(results)} ({pass_rate:.0%})  "
          f"Cost: ${total_cost:.4f}  Report: {report_path}")
    if flaky:
        print(f"Flaky (passed on retry — watch these): {[r['id'] for r in flaky]}")
    for r in results:
        if not r["passed"]:
            reasons = r["check_failures"] or (
                r["judge"]["fabricated_claims"] if r["judge"] else []
            ) or [r["error"] or "judge scores below threshold"]
            print(f"  FAIL {r['id']}: {reasons}")

    if critical_failures:
        print(f"\nGATE FAILED: critical case(s) failed: {[r['id'] for r in critical_failures]}")
        return 1
    if pass_rate < PASS_RATE_GATE:
        print(f"\nGATE FAILED: pass rate {pass_rate:.0%} < {PASS_RATE_GATE:.0%}")
        return 1
    print("\nGATE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
