"""Model bake-off — run the same golden suite across candidate models.

The registry reads model IDs from AI_* env vars, so each candidate runs in
a fresh subprocess with the override applied. Output: a side-by-side table
of pass rate, judge scores, cost, and latency — routing decisions on data
instead of vibes.

    # Which responder writes the best patient answers?
    .venv/bin/python -m evals.bakeoff \\
        --vary AI_REASONING_RESPONDER_MODEL \\
        --models claude-sonnet-4-6,gpt-5.1,gemini-2.5-pro

    # Is a cheaper thinker good enough? (smaller suite for a quick read)
    .venv/bin/python -m evals.bakeoff \\
        --vary AI_REASONING_THINKER_MODEL \\
        --models claude-haiku-4-5-20251001,gpt-4.1-mini \\
        --suite evals/golden/health_query.yaml --case glucose_yesterday --case med_stop

Candidate models must be registered in models/registry.py (the bake-off
checks first). When a new model generation ships: register it, bake it off,
and the table tells you whether to promote it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
from pathlib import Path

_SUITE_DEFAULT = Path(__file__).parent / "golden" / "health_query.yaml"
_REPORT_RE = re.compile(r"Report: (\S+\.json)")


def _check_registered(model_ids: list[str]) -> list[str]:
    from lib.ai_foundation.models.registry import build_default_registry

    registry = build_default_registry()
    known = {spec.model_id for spec in registry.list_models()} if hasattr(registry, "list_models") else set()
    if not known:  # fallback: try get() per model
        missing = []
        for mid in model_ids:
            try:
                registry.get(mid)
            except Exception:
                missing.append(mid)
        return missing
    return [m for m in model_ids if m not in known]


def _run_candidate(env_var: str, model_id: str, suite: Path, cases: list[str]) -> dict | None:
    env = {**os.environ, env_var: model_id}
    cmd = [sys.executable, "-m", "evals.run", "--suite", str(suite)]
    for c in cases:
        cmd += ["--case", c]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=3600)
    match = _REPORT_RE.search(proc.stdout)
    if not match:
        print(f"  {model_id}: run produced no report (exit {proc.returncode})", file=sys.stderr)
        print(proc.stdout[-500:], file=sys.stderr)
        return None
    report = json.loads(Path(match.group(1)).read_text())
    report["_gate_passed"] = proc.returncode == 0
    return report


def _summarize(model_id: str, report: dict) -> dict:
    results = report["results"]
    judged = [r["judge"] for r in results if r.get("judge")]

    def avg(field: str) -> float | None:
        vals = [j[field] for j in judged if j.get(field) is not None]
        return round(statistics.mean(vals), 2) if vals else None

    return {
        "model": model_id,
        "gate": "PASS" if report["_gate_passed"] else "FAIL",
        "pass_rate": f"{report['pass_rate']:.0%}",
        "accuracy": avg("accuracy"),
        "safety": avg("safety"),
        "completeness": avg("completeness"),
        "tone": avg("tone"),
        "flaky": len(report.get("flaky_cases", [])),
        "cost_usd": round(report["total_cost_usd"], 4),
        "p50_latency_ms": int(statistics.median(r["latency_ms"] for r in results)),
        "failed": [r["id"] for r in results if not r["passed"]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the eval suite across candidate models.")
    parser.add_argument("--vary", required=True,
                        help="Env var to vary, e.g. AI_REASONING_RESPONDER_MODEL")
    parser.add_argument("--models", required=True,
                        help="Comma-separated model IDs (must be in models/registry.py)")
    parser.add_argument("--suite", type=Path, default=_SUITE_DEFAULT)
    parser.add_argument("--case", action="append", default=[],
                        help="Limit to specific case IDs (repeatable).")
    args = parser.parse_args()

    model_ids = [m.strip() for m in args.models.split(",") if m.strip()]
    missing = _check_registered(model_ids)
    if missing:
        print(f"Not registered in models/registry.py: {missing} — register them first.",
              file=sys.stderr)
        return 2

    print(f"Bake-off: {args.vary} × {model_ids}  suite={args.suite.name} "
          f"cases={args.case or 'all'}\n")

    rows = []
    for model_id in model_ids:
        print(f"── {model_id} ──")
        report = _run_candidate(args.vary, model_id, args.suite, args.case)
        if report:
            rows.append(_summarize(model_id, report))
            r = rows[-1]
            print(f"  gate={r['gate']} pass={r['pass_rate']} acc={r['accuracy']} "
                  f"safety={r['safety']} cost=${r['cost_usd']} p50={r['p50_latency_ms']}ms")

    if not rows:
        return 1

    print(f"\n{'=' * 100}")
    header = f"{'model':<32}{'gate':<6}{'pass':<7}{'acc':<6}{'safe':<6}{'comp':<6}{'tone':<6}{'flaky':<7}{'cost':<10}{'p50 ms':<8}"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(f"{r['model']:<32}{r['gate']:<6}{r['pass_rate']:<7}"
              f"{r['accuracy'] or '-':<6}{r['safety'] or '-':<6}"
              f"{r['completeness'] or '-':<6}{r['tone'] or '-':<6}"
              f"{r['flaky']:<7}${r['cost_usd']:<9}{r['p50_latency_ms']:<8}")
    for r in rows:
        if r["failed"]:
            print(f"  {r['model']} failed: {r['failed']}")

    out = Path(__file__).parent / "reports" / "bakeoff_latest.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"vary": args.vary, "rows": rows}, indent=2))
    print(f"\nSaved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
