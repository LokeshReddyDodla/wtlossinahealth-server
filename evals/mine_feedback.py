"""Feedback → golden-case miner.

Pulls thumbs-down feedback scores from Langfuse, shows what the agent
actually said, and scaffolds draft golden-case YAML from each failure.
This is how the eval suite grows from REAL patient failures instead of
imagined ones.

    .venv/bin/python -m evals.mine_feedback                 # last 30 days
    .venv/bin/python -m evals.mine_feedback --days 7
    .venv/bin/python -m evals.mine_feedback --score insight_feedback

Workflow: run it, read each failure, decide whether it represents a failure
CLASS worth locking, copy the scaffolded case into the right golden/*.yaml,
ground the expectations in fixtures, and re-run the suite.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from datetime import datetime, timedelta, timezone

# Feedback score names logged by the API layer (0.0 = thumbs down)
_SCORE_NAMES = ("user_feedback", "insight_feedback")


def _client():
    from dotenv import load_dotenv
    load_dotenv()

    from lib.ai_foundation.config import settings

    if not settings.LANGFUSE_PUBLIC_KEY:
        print("LANGFUSE_PUBLIC_KEY not configured — nothing to mine.", file=sys.stderr)
        sys.exit(2)

    from langfuse import Langfuse
    return Langfuse(
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
        host=settings.LANGFUSE_HOST,
    )


def _wrap(text: str, indent: str = "      ") -> str:
    return "\n".join(
        textwrap.fill(line, width=90, initial_indent=indent, subsequent_indent=indent)
        for line in (text or "").splitlines()
        if line.strip()
    )


def mine(days: int, score_names: tuple[str, ...], limit: int) -> int:
    lf = _client()
    since = datetime.now(timezone.utc) - timedelta(days=days)

    found = 0
    for score_name in score_names:
        try:
            page = lf.api.score.get(
                name=score_name,
                operator="=",
                value=0.0,  # thumbs down
                from_timestamp=since,
                limit=limit,
            )
        except Exception as exc:
            print(f"[{score_name}] fetch failed: {exc}", file=sys.stderr)
            continue

        for score in page.data:
            trace_id = getattr(score, "trace_id", None)
            if not trace_id:
                continue
            found += 1

            question, response = "(trace fetch failed)", ""
            try:
                trace = lf.fetch_trace(trace_id).data
                question = str(trace.input or "")[:500]
                response = str(trace.output or "")[:700]
            except Exception as exc:
                question = f"(trace fetch failed: {exc})"

            comment = getattr(score, "comment", None)
            ts = getattr(score, "timestamp", None)

            print("=" * 78)
            print(f"THUMBS DOWN  [{score_name}]  {ts}  trace={trace_id}")
            if comment:
                print(f"user comment: {comment}")
            print("\n--- what the patient asked / input ---")
            print(_wrap(question, "  "))
            print("\n--- what the agent said ---")
            print(_wrap(response, "  "))
            print("\n--- draft golden case (edit + move into evals/golden/*.yaml) ---")
            case_id = f"mined_{(ts or datetime.now(timezone.utc)):%Y%m%d}_{trace_id[:8]}"
            print(textwrap.dedent(f"""\
                  - id: {case_id}
                    category: mined_from_feedback
                    query: {question.splitlines()[0][:120] if question else 'FILL_ME'!r}
                    checks:
                      must_mention: []      # what SHOULD the answer contain?
                      must_not_mention: []  # what did the bad answer do wrong?
                    criteria: >
                      Mined from thumbs-down trace {trace_id}.
                      The agent previously failed by: FILL_ME (describe the failure).
                      A good response must: FILL_ME.
            """))

    print("=" * 78)
    if found == 0:
        print(f"No thumbs-down feedback in the last {days} days. 🎉")
    else:
        print(f"{found} failure(s) shown. Convert the ones that represent a failure "
              f"CLASS into golden cases — skip one-off noise.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Mine thumbs-down feedback into draft eval cases.")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=50, help="Max scores per feedback type.")
    parser.add_argument(
        "--score", action="append",
        help=f"Score name(s) to mine (default: {', '.join(_SCORE_NAMES)}).",
    )
    args = parser.parse_args()
    names = tuple(args.score) if args.score else _SCORE_NAMES
    return mine(args.days, names, args.limit)


if __name__ == "__main__":
    sys.exit(main())
