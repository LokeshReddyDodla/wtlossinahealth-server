#!/usr/bin/env python3
"""
Eval Baseline Runner — execute the 50 golden cases against the live model
and print baseline metrics for intent extraction accuracy.

Usage:
    OPENAI_API_KEY=sk-... python scripts/run_eval_baseline.py

    Options:
        --model gpt-4.1-mini    Model to evaluate (default: gpt-4.1-mini)
        --cases N               Max cases to run (default: all)
        --verbose               Print per-case results
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def main(model_id: str, max_cases: int | None, verbose: bool):
    from lib.ai_foundation.models.registry import build_default_registry, ModelTask
    from lib.ai_foundation.models.gateway import ModelGateway
    from lib.ai_foundation.eval.runners.intent_eval import IntentEvalRunner, load_eval_cases
    from lib.ai_foundation.agents.health_query.contracts import QueryIntent
    from lib.ai_foundation.prompts.registry import PromptRegistry

    # Load prompts
    prompts = PromptRegistry()
    prompts_dir = Path("lib/ai_foundation/agents/health_query/prompts")
    prompts.register_directory(prompts_dir, namespace="health_query")

    # Build system + intent prompt
    system_prompt = prompts.get("hq_system_patient").render(current_time="2026-03-24 12:00 UTC")
    intent_prompt = prompts.get("hq_intent_extraction").body
    combined_prompt = f"{system_prompt}\n\n{intent_prompt}"

    # Build gateway
    registry = build_default_registry()
    gateway = ModelGateway(registry=registry)

    # Build runner
    runner = IntentEvalRunner(
        gateway=gateway,
        system_prompt=combined_prompt,
        response_model=QueryIntent,
    )

    # Load cases
    cases_path = Path("lib/ai_foundation/eval/datasets/intent_golden_cases.jsonl")
    cases = load_eval_cases(cases_path)
    if max_cases:
        cases = cases[:max_cases]

    print(f"Running {len(cases)} eval cases against {model_id}...")
    print("=" * 60)

    # Run evaluation
    summary = await runner.run(cases, model_id=model_id, prompt_version="v1.0")

    # Print results
    print()
    print(summary.summary_line())
    print()
    print(f"  Total cases:  {summary.total_cases}")
    print(f"  Passed:       {summary.passed_cases}")
    print(f"  Failed:       {summary.failed_cases}")
    print(f"  Errors:       {summary.error_cases}")
    print(f"  Pass rate:    {summary.pass_rate:.1%}")
    print(f"  Avg latency:  {summary.avg_latency_ms:.0f}ms")
    print(f"  Total cost:   ${summary.total_cost_usd or 0:.4f}")
    print()

    # Per-metric breakdown
    if summary.metrics:
        print("Per-metric scores:")
        for metric, score in sorted(summary.metrics.items()):
            status = "PASS" if score >= 0.8 else "FAIL"
            print(f"  {metric:30s} {score:.2%}  [{status}]")
        print()

    # Failed cases detail
    if verbose:
        failed = [r for r in summary.results if not r.passed]
        if failed:
            print(f"Failed cases ({len(failed)}):")
            print("-" * 60)
            for r in failed:
                case = next((c for c in cases if c.case_id == r.case_id), None)
                print(f"\n  {r.case_id}: {case.input_query if case else '?'}")
                for v in r.verdicts:
                    status = "PASS" if v.passed else "FAIL"
                    print(f"    [{status}] {v.metric_name}: {v.score:.2f} (threshold={v.threshold})")
                    if v.details:
                        print(f"           {v.details}")
                if r.error:
                    print(f"    ERROR: {r.error}")
            print()

    # Save results to file
    output_path = Path("scripts/eval_baseline_results.json")
    output_path.write_text(json.dumps(
        summary.model_dump(mode="json", exclude={"results"}),
        indent=2, default=str,
    ))
    print(f"Results saved to {output_path}")

    return summary.pass_rate


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run eval baseline")
    parser.add_argument("--model", default="gpt-4.1-mini", help="Model to evaluate")
    parser.add_argument("--cases", type=int, default=None, help="Max cases to run")
    parser.add_argument("--verbose", action="store_true", help="Print per-case details")
    args = parser.parse_args()

    pass_rate = asyncio.run(main(args.model, args.cases, args.verbose))
    sys.exit(0 if pass_rate >= 0.7 else 1)
