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


def _load_suite(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["cases"]


async def _run_case(case: dict[str, Any], *, no_judge: bool) -> dict[str, Any]:
    from lib.ai_foundation.agents.state import AgentContext, AgentInput

    from .agent_factory import build_eval_agent, shared_gateway
    from .checks import run_checks
    from .fixtures import (
        EVAL_PATIENT_ID,
        EVAL_TIMEZONE,
        default_facts,
        default_records,
    )
    from .judge import judge_case

    records = default_records() if case.get("fixture", "default") == "default" else []
    facts = default_facts() if case.get("fixture", "default") == "default" else []
    agent = build_eval_agent(records, facts)

    local_time = datetime.now(ZoneInfo(EVAL_TIMEZONE)).strftime("%Y-%m-%d %H:%M (%A)")
    agent_input = AgentInput(
        message=case["query"],
        context=AgentContext(
            patient_id=EVAL_PATIENT_ID,
            user_id=EVAL_PATIENT_ID,
            user_role="patient",
            thread_id=f"eval:{case['id']}",
            patient_ids=[EVAL_PATIENT_ID],
            metadata={"local_time": local_time},
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
            judgment = await judge_case(
                shared_gateway(),
                question=case["query"],
                response=response,
                fixture_texts=[r["text_repr"] for r in records],
                facts=[f"{f.key}: {f.value}" for f in facts],
                criteria=case.get("criteria", ""),
            )
        except Exception as exc:
            error = f"judge failed: {exc}"

    passed = (
        error is None
        and check_result.passed
        and (no_judge or judgment is None or judgment.passed)
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


async def _run_suite(cases: list[dict[str, Any]], *, no_judge: bool) -> list[dict[str, Any]]:
    sem = asyncio.Semaphore(CONCURRENCY)

    async def bounded(case: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            result = await _run_case(case, no_judge=no_judge)
            marker = "PASS" if result["passed"] else "FAIL"
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

    cases = _load_suite(args.suite)
    if args.case:
        cases = [c for c in cases if c["id"] in set(args.case)]
        if not cases:
            print(f"No cases match {args.case}", file=sys.stderr)
            return 2

    if args.list:
        for c in cases:
            crit = " [critical]" if c.get("critical") else ""
            print(f"  {c['id']:<22} {c.get('category', ''):<14}{crit}  {c['query'][:60]}")
        return 0

    print(f"Running {len(cases)} eval cases (judge={'off' if args.no_judge else 'on'})...")
    results = asyncio.run(_run_suite(cases, no_judge=args.no_judge))

    passed = [r for r in results if r["passed"]]
    critical_failures = [r for r in results if r["critical"] and not r["passed"]]
    pass_rate = len(passed) / len(results) if results else 0.0
    total_cost = sum(r["cost_usd"] for r in results)

    _REPORTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = _REPORTS_DIR / f"eval_{stamp}.json"
    report = {
        "timestamp": stamp,
        "suite": str(args.suite),
        "pass_rate": round(pass_rate, 3),
        "total_cost_usd": round(total_cost, 4),
        "critical_failures": [r["id"] for r in critical_failures],
        "results": results,
    }
    report_path.write_text(json.dumps(report, indent=2, default=str))

    print(f"\n{'=' * 60}")
    print(f"Pass rate: {len(passed)}/{len(results)} ({pass_rate:.0%})  "
          f"Cost: ${total_cost:.4f}  Report: {report_path}")
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
