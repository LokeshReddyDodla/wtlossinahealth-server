"""Cohort agent tools (Python). Each returns compact JSON — counts/IDs/rows,
never thousands of raw records — so the agent scales to the whole panel.

Tools read the per-request :class:`CohortContext` (which holds the authenticated
loopback client) via the injected ``RunContextWrapper``.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import io
import json
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from agents import RunContextWrapper, function_tool

from .client import InternalAPIClient


@dataclass
class CohortContext:
    """Per-request context passed to ``Runner.run(..., context=...)``."""

    client: InternalAPIClient
    _names: dict[str, str] = field(default_factory=dict)


def _client(ctx: RunContextWrapper["CohortContext"]) -> InternalAPIClient:
    return ctx.context.client


def _compact(obj: Any, limit: int = 10000) -> str:
    s = json.dumps(obj, default=str)
    return s if len(s) <= limit else s[:limit] + f"... [truncated, {len(s)} chars]"


async def _name_map(ctx: RunContextWrapper["CohortContext"]) -> dict[str, str]:
    cache = ctx.context._names
    if not cache:
        data = await _client(ctx).get("/v1/patients", {"limit": 1000})
        items = data.get("items", []) if isinstance(data, dict) else (data or [])
        for it in items:
            if it.get("patient_id"):
                cache[it["patient_id"]] = (it.get("full_name") or "").strip()
    return cache


async def _pname(ctx: RunContextWrapper["CohortContext"], r: dict[str, Any]) -> str:
    pid = str(r.get("patient_id", ""))
    nm = (await _name_map(ctx)).get(pid)
    if nm:
        return nm
    pi = r.get("patient") or {}
    return pi.get("full_name") or f"{pi.get('first_name','')} {pi.get('last_name','')}".strip() or pid[:8]


async def _pull_cgm(ctx: RunContextWrapper["CohortContext"], metric: str, days: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = await _client(ctx).get(f"/dashboard/metrics/cgm/{metric}", {"days": days, "limit": 200, "offset": offset})
        items = page.get("items", page) if isinstance(page, dict) else page
        if not items:
            break
        rows += items
        if len(items) < 200:
            break
        offset += 200
    return rows


# ── directory ─────────────────────────────────────────────────────────────────
@function_tool
async def list_patients(ctx: RunContextWrapper["CohortContext"], limit: int = 1000, search: str = "") -> str:
    """List patients under the care provider (patient_id, name, age, gender, last_active_at)."""
    params: dict[str, Any] = {"limit": limit, "order_by": "last_active_at", "order": "desc"}
    if search:
        params["search"] = search
    data = await _client(ctx).get("/v1/patients", params)
    items = data.get("items", []) if isinstance(data, dict) else (data or [])
    slim = [
        {"patient_id": it.get("patient_id"), "name": it.get("full_name"), "age": it.get("age"),
         "gender": it.get("gender"), "last_active_at": it.get("last_active_at")}
        for it in items
    ]
    return _compact({"total": data.get("total", len(slim)) if isinstance(data, dict) else len(slim),
                     "returned": len(slim), "patients": slim})


@function_tool
async def get_patient(ctx: RunContextWrapper["CohortContext"], patient_id: str) -> str:
    """Full profile for one patient (demographics, diabetic_history, packages, reports, ...)."""
    data = await _client(ctx).get(f"/care-providers/patients/{patient_id}")
    # Strip contact PHI before it reaches the (third-party) LLM context/logs;
    # no cohort question needs phone/email/address.
    if isinstance(data, dict):
        for _k in ("phone", "phone_number", "mobile", "mobile_number",
                   "whatsapp_number", "email", "address", "emergency_contact"):
            data.pop(_k, None)
    return _compact(data, 8000)


@function_tool
async def get_medications(ctx: RunContextWrapper["CohortContext"], patient_id: str) -> str:
    """Active/paused/as-needed/completed medications for a patient."""
    return _compact(await _client(ctx).get(f"/v1/medications/{patient_id}"))


@function_tool
async def cohort_demographics(ctx: RunContextWrapper["CohortContext"]) -> str:
    """Age + gender + BMI breakdown across the whole panel in one call."""
    data = await _client(ctx).get("/v1/patients", {"limit": 1000})
    items = data.get("items", []) if isinstance(data, dict) else (data or [])
    gender: dict[str, int] = {}
    bands = {"<30": 0, "30-39": 0, "40-49": 0, "50-59": 0, "60-69": 0, "70+": 0, "unknown": 0}
    age_sum = 0.0
    age_n = 0
    bmis: list[float] = []
    for it in items:
        g = str(it.get("gender") or "unknown")
        gender[g] = gender.get(g, 0) + 1
        age = it.get("age") if isinstance(it.get("age"), (int, float)) else None
        if age is None:
            bands["unknown"] += 1
        else:
            age_sum += age
            age_n += 1
            b = "<30" if age < 30 else "30-39" if age < 40 else "40-49" if age < 50 else "50-59" if age < 60 else "60-69" if age < 70 else "70+"
            bands[b] += 1
        h, w = it.get("height_cm"), it.get("weight_kg")
        if h and w:
            bmi = w / (h / 100) ** 2
            if 5 < bmi < 80:
                bmis.append(bmi)
    bmis.sort()
    return _compact({
        "total": data.get("total", len(items)) if isinstance(data, dict) else len(items),
        "gender": gender, "age_bands": bands,
        "average_age": round(age_sum / age_n, 1) if age_n else None,
        "bmi": {"n": len(bmis), "median": round(bmis[len(bmis) // 2], 1) if bmis else None},
    })


# ── CGM ───────────────────────────────────────────────────────────────────────
@function_tool
async def cgm_hyper_patients(ctx: RunContextWrapper["CohortContext"], days: int = 30) -> str:
    """All patients with hyperglycemic spike events in `days`: name, spike_events, peak_glucose, days_affected."""
    agg: dict[str, dict[str, Any]] = defaultdict(lambda: {"name": None, "events": 0, "peak": 0, "days": set()})
    for r in await _pull_cgm(ctx, "hyper-patients", days):
        a = agg[r["patient_id"]]
        a["name"] = await _pname(ctx, r)
        a["days"].add(str(r.get("date"))[:10])
        for ev in r.get("hyper_events", []):
            a["events"] += 1
            a["peak"] = max(a["peak"], ev.get("peak_glucose_mgdl") or 0)
    out = sorted(({"name": a["name"], "patient_id": pid, "spike_events": a["events"],
                   "peak_glucose": round(a["peak"]), "days_affected": len(a["days"])}
                  for pid, a in agg.items()), key=lambda x: -x["peak_glucose"])
    return _compact({"window_days": days, "patient_count": len(out), "patients": out})


@function_tool
async def cgm_hypo_patients(ctx: RunContextWrapper["CohortContext"], days: int = 30) -> str:
    """All patients with hypoglycemic (<70) events in `days`: name, low_events, lowest_glucose, days_affected."""
    agg: dict[str, dict[str, Any]] = defaultdict(lambda: {"name": None, "events": 0, "lowest": 999, "days": set()})
    for r in await _pull_cgm(ctx, "hypo-patients", days):
        a = agg[r["patient_id"]]
        a["name"] = await _pname(ctx, r)
        a["days"].add(str(r.get("date"))[:10])
        for ev in r.get("hypo_events", []):
            a["events"] += 1
            a["lowest"] = min(a["lowest"], ev.get("lowest_glucose_mgdl") or 999)
    out = sorted(({"name": a["name"], "patient_id": pid, "low_events": a["events"],
                   "lowest_glucose": round(a["lowest"]), "days_affected": len(a["days"])}
                  for pid, a in agg.items()), key=lambda x: x["lowest_glucose"])
    return _compact({"window_days": days, "patient_count": len(out), "patients": out})


@function_tool
async def cgm_high_gv_patients(ctx: RunContextWrapper["CohortContext"], days: int = 30) -> str:
    """All patients with high glucose variability in `days`: name, max_variability, days_affected."""
    agg: dict[str, dict[str, Any]] = defaultdict(lambda: {"name": None, "gv": 0.0, "days": set()})
    for r in await _pull_cgm(ctx, "high-gv-patients", days):
        a = agg[r["patient_id"]]
        a["name"] = await _pname(ctx, r)
        a["days"].add(str(r.get("date"))[:10])
        if r.get("glucose_variability") is not None:
            a["gv"] = max(a["gv"], r["glucose_variability"])
    out = sorted(({"name": a["name"], "patient_id": pid, "max_variability": round(a["gv"], 1),
                   "days_affected": len(a["days"])} for pid, a in agg.items()),
                 key=lambda x: -x["max_variability"])
    return _compact({"window_days": days, "patient_count": len(out), "patients": out})


@function_tool
async def cgm_glycemic_summary(ctx: RunContextWrapper["CohortContext"], days: int = 14) -> str:
    """Glycemic classification for every CGM patient: mean glucose -> GMI (est. A1c =
    3.31 + 0.02392*mean), classified diabetes (>=6.5%), prediabetes (5.7-6.4%) or normal."""
    reads: dict[str, dict[str, float]] = defaultdict(dict)
    names: dict[str, str] = {}
    for metric in ("hyper-patients", "high-gv-patients", "hypo-patients"):
        for r in await _pull_cgm(ctx, metric, days):
            pid = r["patient_id"]
            names[pid] = await _pname(ctx, r)
            for x in r.get("cgm_readings", []):
                if x.get("glucose_mgdl") is not None and x.get("device_timestamp"):
                    reads[pid][x["device_timestamp"]] = x["glucose_mgdl"]
    counts = {"diabetes": 0, "prediabetes": 0, "normal": 0}
    rows: list[dict[str, Any]] = []
    for pid, series in reads.items():
        gl = list(series.values())
        if len(gl) < 20:
            continue
        mean = statistics.mean(gl)
        gmi = 3.31 + 0.02392 * mean
        cls = "diabetes" if gmi >= 6.5 else "prediabetes" if gmi >= 5.7 else "normal"
        counts[cls] += 1
        rows.append({"name": names.get(pid, pid[:8]), "patient_id": pid, "mean_glucose": round(mean),
                     "gmi": round(gmi, 1), "estimated_a1c": round(gmi, 1),
                     "time_above_180_pct": round(100 * sum(g > 180 for g in gl) / len(gl)), "class": cls})
    rows.sort(key=lambda x: -x["gmi"])
    return _compact({"window_days": days, "cgm_patients_analyzed": len(rows), "counts": counts, "patients": rows}, 12000)


@function_tool
async def cgm_spike_timing(ctx: RunContextWrapper["CohortContext"], days: int = 14, min_events: int = 1) -> str:
    """Root-cause helper: bins hyper-event start-times into time-of-day buckets across the
    cohort and per patient. Use for 'what time of day do spikes cluster / common pattern'."""
    def bucket(h: int) -> str:
        return ("night (00-06)" if h < 6 else "morning (06-11)" if h < 11 else "midday (11-14)"
                if h < 14 else "afternoon (14-17)" if h < 17 else "evening (17-22)" if h < 22 else "late (22-24)")
    per_patient: dict[str, list[int]] = defaultdict(list)
    names: dict[str, str] = {}
    for r in await _pull_cgm(ctx, "hyper-patients", days):
        names[r["patient_id"]] = await _pname(ctx, r)
        for ev in r.get("hyper_events", []):
            ts = ev.get("start_time")
            if ts:
                with contextlib.suppress(ValueError, IndexError):
                    per_patient[r["patient_id"]].append(int(str(ts)[11:13]))
    cohort: Counter = Counter()
    patients: list[dict[str, Any]] = []
    for pid, hours in per_patient.items():
        if len(hours) < min_events:
            continue
        b = Counter(bucket(h) for h in hours)
        cohort.update(b)
        patients.append({"name": names.get(pid), "spike_events": len(hours),
                         "peak_bucket": b.most_common(1)[0][0], "buckets": dict(b)})
    total = sum(cohort.values())
    dist = sorted(({"window": k, "events": v, "pct": round(100 * v / total)} for k, v in cohort.items()),
                  key=lambda x: -x["events"]) if total else []
    patients.sort(key=lambda x: -x["spike_events"])
    return _compact({"window_days": days, "patients_with_spikes": len(patients),
                     "total_spike_events": total, "time_of_day_distribution": dist,
                     "per_patient": patients[:40]}, 11000)


# ── meals ─────────────────────────────────────────────────────────────────────
@function_tool
async def meal_logging_regularity(ctx: RunContextWrapper["CohortContext"], start_date: str, end_date: str, top: int = 50) -> str:
    """Per-patient meal-logging regularity (days logged, total meals, meals/day) between
    start_date and end_date (YYYY-MM-DD), with daily/regular/occasional/sparse tier counts."""
    agg: dict[str, dict[str, Any]] = defaultdict(lambda: {"days": set(), "meals": 0, "name": None})
    offset = 0
    total = 0
    while True:
        page = await _client(ctx).get("/dashboard/metrics/meals/filter-macro",
                                 {"start": start_date, "end": end_date, "limit": 300, "offset": offset})
        rows = page if isinstance(page, list) else page.get("items", [])
        if not rows:
            break
        for m in rows:
            pid = m.get("patient_id")
            if not pid:
                continue
            a = agg[pid]
            a["days"].add(m.get("date"))
            a["meals"] += 1
            pi = m.get("patient") or {}
            nm = pi.get("full_name") or f"{pi.get('first_name','')} {pi.get('last_name','')}".strip()
            if nm:
                a["name"] = nm
        total += len(rows)
        if len(rows) < 300:
            break
        offset += 300
    ranked = sorted(({"name": a["name"] or pid[:8], "days_logged": len(a["days"]), "meals": a["meals"],
                      "meals_per_day": round(a["meals"] / max(len(a["days"]), 1), 1)}
                     for pid, a in agg.items()), key=lambda x: (-x["days_logged"], -x["meals"]))
    tiers = {"daily": 0, "regular": 0, "occasional": 0, "sparse": 0}
    for rr in ranked:
        d = rr["days_logged"]
        tiers["daily" if d >= 25 else "regular" if d >= 15 else "occasional" if d >= 7 else "sparse"] += 1
    return _compact({"window": f"{start_date}..{end_date}", "meals_counted": total,
                     "patients_logging": len(ranked), "tiers": tiers, "top": ranked[:top]}, 9000)


# ── in-app engagement ─────────────────────────────────────────────────────────
# Per-patient log endpoints; all return a `total` so limit=1 gives the count.
_ENGAGEMENT_ENDPOINTS = {
    "workouts": "/v1/patients/{pid}/workouts",
    "sleep": "/v1/patients/{pid}/checkins/sleep",
    "mood": "/v1/patients/{pid}/checkins/mood",
    "symptoms": "/v1/patients/{pid}/checkins/symptoms",
}


def _log_total(data: Any) -> int:
    if isinstance(data, dict):
        if isinstance(data.get("total"), int):
            return data["total"]
        for v in data.values():
            if isinstance(v, list):
                return len(v)
    return len(data) if isinstance(data, list) else 0


@function_tool
async def app_engagement_summary(
    ctx: RunContextWrapper["CohortContext"], days: int = 30, activities: str = "workouts", top: int = 25
) -> str:
    """How many patients are logging in-app activities and how much, over the last
    `days`. activities is a comma list from: workouts, sleep, mood, symptoms.
    Returns per-activity: patients_logging, total_logs, and the top loggers.
    Use for 'how many users log workouts / sleep / mood / symptoms', engagement,
    app usage, adherence-to-logging questions."""
    import asyncio

    acts = [a.strip().lower() for a in activities.split(",") if a.strip()]
    bad = [a for a in acts if a not in _ENGAGEMENT_ENDPOINTS]
    if bad or not acts:
        return f"ERROR: unknown activities {bad or acts}; choose from {sorted(_ENGAGEMENT_ENDPOINTS)}"
    end = _dt.date.today()
    start = end - _dt.timedelta(days=days)
    names = await _name_map(ctx)
    pids = list(names)
    # Bounded fan-out: these loop back to this server, so keep concurrency low.
    sem = asyncio.Semaphore(10)

    async def count(pid: str, act: str) -> tuple[str, str, int]:
        path = _ENGAGEMENT_ENDPOINTS[act].format(pid=pid)
        params = {"start_date": start.isoformat(), "end_date": end.isoformat(), "limit": 1}
        async with sem:
            try:
                return pid, act, _log_total(await _client(ctx).get(path, params))
            except Exception:  # noqa: BLE001 - one bad patient must not sink the sweep
                return pid, act, 0

    rows = await asyncio.gather(*(count(p, a) for p in pids for a in acts))
    out: dict[str, Any] = {}
    for act in acts:
        per = [(pid, n) for pid, a, n in rows if a == act and n > 0]
        per.sort(key=lambda x: -x[1])
        out[act] = {
            "patients_logging": len(per),
            "total_logs": sum(n for _, n in per),
            "top": [{"name": names.get(pid) or pid[:8], "logs": n} for pid, n in per[:top]],
        }
    return _compact({"window_days": days, "panel_size": len(pids), "activities": out}, 11000)


# ── flexible escape hatches ─────────────────────────────────────────────────────
@function_tool
async def list_api_endpoints(ctx: RunContextWrapper["CohortContext"], search: str = "") -> str:
    """Discover REAL backend GET endpoints (path + summary) from the server's
    OpenAPI spec. Call this BEFORE api_get/run_python whenever you are not sure
    a path exists — never guess paths, and never conclude data is unavailable
    from a 404 on a guessed path. `search` filters by substring
    (e.g. 'workout', 'sleep', 'vitals', 'timeline')."""
    spec = await _client(ctx).get("/openapi.json")
    q = search.lower()
    rows: list[str] = []
    for path, methods in (spec.get("paths") or {}).items():
        op = methods.get("get") if isinstance(methods, dict) else None
        if not isinstance(op, dict):
            continue
        summary = op.get("summary") or ""
        if q and q not in path.lower() and q not in summary.lower():
            continue
        rows.append(f"GET {path} — {summary}".rstrip(" —"))
    rows.sort()
    if not rows:
        return f"No GET endpoints matching '{search}'. Try a shorter search term."
    return _compact({"count": len(rows), "endpoints": rows[:150]})


@function_tool
async def api_get(ctx: RunContextWrapper["CohortContext"], path: str, params_json: str = "{}") -> str:
    """Call ANY backend GET endpoint and return its JSON. path like '/v1/patients'. params_json
    is a JSON object of query params. Use when no specific tool fits; find valid
    paths with list_api_endpoints first (per-patient data usually lives under
    '/v1/patients/{patient_id}/...')."""
    try:
        params = json.loads(params_json) if params_json else {}
    except json.JSONDecodeError as e:
        return f"ERROR: params_json is not valid JSON: {e}"
    return _compact(await _client(ctx).get(path, params), 12000)


@function_tool
async def run_python(ctx: RunContextWrapper["CohortContext"], code: str) -> str:
    """Run short Python to fetch and compute over API data, then PRINT the result.
    In scope: ``api_get(path, params=None)`` (authenticated, returns parsed JSON;
    list endpoints like '/v1/patients' return {'total':..,'items':[...]}), plus
    ``json``, ``statistics``, ``datetime``, ``collections``, ``Counter``,
    ``defaultdict``, ``math``. Only what you PRINT is returned — print a concise
    summary, never raw records. Use for custom aggregation (GMI, joins, etc.)."""
    import asyncio
    import collections
    import math

    client = _client(ctx)
    loop = asyncio.get_running_loop()

    def api_get_sync(path, params=None):
        # exec runs in a worker thread; hop each API call back onto the loop
        # (the loop must stay free — these calls loop back to THIS server).
        return asyncio.run_coroutine_threadsafe(client.get(path, params), loop).result(timeout=60)

    # SECURITY: an empty/absent __builtins__ makes exec inject the FULL builtins
    # (__import__, open, eval), i.e. arbitrary code + filesystem + os.environ in
    # the server process. Pin a minimal, side-effect-free set instead.
    _safe_builtins = {
        b.__name__: b for b in (
            len, range, min, max, sum, sorted, abs, round, any, all,
            enumerate, zip, map, filter, str, int, float, bool, dict,
            list, set, tuple, isinstance, repr,
        )
    }
    _safe_builtins["print"] = print
    scope: dict[str, Any] = {
        "__builtins__": _safe_builtins,
        "api_get": api_get_sync,
        "json": json, "statistics": statistics, "datetime": _dt, "collections": collections,
        "Counter": collections.Counter, "defaultdict": collections.defaultdict, "math": math,
    }
    buf = io.StringIO()

    def _run() -> str | None:
        try:
            with contextlib.redirect_stdout(buf):
                exec(code, scope)  # noqa: S102 - trusted operator tool, gated by care-provider auth
        except SystemExit:
            return (buf.getvalue() + "\n[run_python: code called exit(); treated as end of script]").strip()
        except BaseException as e:  # noqa: BLE001 - keep the agent loop alive
            return f"{buf.getvalue()}\nERROR: {type(e).__name__}: {e}"
        return None

    try:
        early = await asyncio.wait_for(asyncio.to_thread(_run), timeout=90)
    except asyncio.TimeoutError:
        return "ERROR: run_python timed out after 90s (possible infinite loop)"
    if early is not None:
        return early
    out = buf.getvalue().strip()
    return out[:8000] if out else "(no output printed)"


ALL_TOOLS = [
    list_patients,
    get_patient,
    get_medications,
    cohort_demographics,
    cgm_hyper_patients,
    cgm_hypo_patients,
    cgm_high_gv_patients,
    cgm_glycemic_summary,
    cgm_spike_timing,
    meal_logging_regularity,
    app_engagement_summary,
    list_api_endpoints,
    api_get,
    run_python,
]
