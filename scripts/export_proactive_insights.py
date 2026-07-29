"""Export all proactive-insight traces from Langfuse to JSON.

Reuses the app's own Langfuse settings (lib.ai_foundation.config). Run from the
repo root:

    .venv/bin/python scripts/export_proactive_insights.py [DAYS_BACK] [OUT.json]

DAYS_BACK defaults to 30, OUT defaults to proactive_insights.json. Filters on
trace name="proactive" (HealthQueryAgent.run_proactive), the name every
proactive insight is traced under.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.ai_foundation.config import settings  # noqa: E402
from langfuse import Langfuse  # noqa: E402

days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("proactive_insights.json")

client = Langfuse(
    public_key=settings.LANGFUSE_PUBLIC_KEY,
    secret_key=settings.LANGFUSE_SECRET_KEY,
    host=settings.LANGFUSE_HOST,
)
from_ts = datetime.now(timezone.utc) - timedelta(days=days)
print(f"host={settings.LANGFUSE_HOST}  window={days}d  name=proactive")

traces, page = [], 1
while True:
    resp = client.fetch_traces(name="proactive", from_timestamp=from_ts, page=page, limit=100)
    if not resp.data:
        break
    # SDK objects expose .dict() (pydantic); fall back to __dict__.
    traces.extend(t.dict() if hasattr(t, "dict") else vars(t) for t in resp.data)
    print(f"  page {page}: +{len(resp.data)} (total {len(traces)})")
    page += 1

out.write_text(json.dumps(traces, indent=2, default=str))
print(f"wrote {len(traces)} traces -> {out}")
