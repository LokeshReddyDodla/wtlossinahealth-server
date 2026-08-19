"""Audit Langfuse for $0 / mispriced generations, grouped by model.

Reuses the app's own Langfuse settings (lib.ai_foundation.config). Run from the
repo root:

    .venv/bin/python scripts/langfuse_zero_cost.py [DAYS_BACK]

DAYS_BACK defaults to 7. A row with tokens>0 but cost==0 means LiteLLM's
response_cost didn't attach AND the self-hosted Langfuse model table has no
matching definition, so the generation fell through to $0.
"""
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow running from anywhere: put repo root (parent of scripts/) on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.ai_foundation.config import settings  # noqa: E402
from langfuse import Langfuse  # noqa: E402

days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
client = Langfuse(
    public_key=settings.LANGFUSE_PUBLIC_KEY,
    secret_key=settings.LANGFUSE_SECRET_KEY,
    host=settings.LANGFUSE_HOST,
)
print(f"host={settings.LANGFUSE_HOST}  window={days}d")

from_ts = datetime.now(timezone.utc) - timedelta(days=days)


def g(obj, *names, default=0):
    """First present attribute among names (SDK alias drift), coerced to number."""
    for n in names:
        v = getattr(obj, n, None)
        if v is not None:
            return v
    return default


# per model: [gens, zero_cost_gens_with_tokens, total_tokens, total_cost]
stats = defaultdict(lambda: [0, 0, 0, 0.0])
page, total = 1, 0
while True:
    resp = client.fetch_observations(type="GENERATION", from_start_time=from_ts,
                                      page=page, limit=100)
    rows = resp.data
    if not rows:
        break
    for o in rows:
        model = getattr(o, "model", None) or "(none)"
        tokens = g(o, "total_tokens", "totalTokens")
        cost = float(g(o, "calculated_total_cost", "calculatedTotalCost",
                       "total_cost", "totalCost", default=0.0) or 0.0)
        s = stats[model]
        s[0] += 1
        if tokens and cost <= 1e-9:
            s[1] += 1
        s[2] += int(tokens or 0)
        s[3] += cost
    total += len(rows)
    if len(rows) < 100:
        break
    page += 1

if not stats:
    print("no generations in window")
    sys.exit(0)

print(f"\n{'model':34} {'gens':>6} {'$0(tok>0)':>10} {'tokens':>12} {'cost$':>12}")
print("-" * 78)
zero_total = 0
for model, (gens, zero, toks, cost) in sorted(stats.items(), key=lambda kv: -kv[1][1]):
    zero_total += zero
    flag = "  <-- MISPRICED" if zero else ""
    print(f"{model:34} {gens:>6} {zero:>10} {toks:>12,} {cost:>12.4f}{flag}")
print("-" * 78)
print(f"{'TOTAL':34} {total:>6} {zero_total:>10}")
print(f"\n{zero_total}/{total} generations have tokens but $0 cost "
      f"({100*zero_total/total:.1f}%) — these bypassed ingested cost and hit the "
      f"self-hosted model table.")
