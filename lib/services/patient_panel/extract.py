"""Pure mappers from source documents to PanelInputs fields."""

from __future__ import annotations

from typing import Any


def _add(*vals: float | None) -> float | None:
    present = [v for v in vals if v is not None]
    return round(sum(present), 1) if present else None


def cgm_inputs(report: dict[str, Any] | None) -> dict[str, Any]:
    if not report:
        return {}
    s = report.get("cgm_summary_stats") or {}
    r = report.get("cgm_range_stats") or {}
    tr = report.get("trend") or {}

    tir = r.get("in_target_70_180_percent")
    if tir is None:
        tir = r.get("in_target_63_140_percent")

    above_180 = _add(r.get("above_180_below_250_percent"), r.get("above_250_percent"))
    below_70 = _add(r.get("below_70_above_54_percent"), r.get("below_54_percent"))
    hypo = report.get("hypo_events")

    return {
        "tir_pct": tir,
        "avg_glucose": s.get("average_glucose_mgdl"),
        "cv_pct": s.get("coefficient_of_variation_percent"),
        "gmi": s.get("gmi"),
        "below_54_pct": r.get("below_54_percent"),
        "below_70_pct": below_70,
        "above_180_pct": above_180,
        "nocturnal_below_70_pct": s.get("nocturnal_time_below_70_percent"),
        "tir_delta": tr.get("delta_time_in_range_percent"),
        "hypo_events": len(hypo) if isinstance(hypo, list) else None,
    }


_AGG_FIELDS = (
    "tir_pct", "avg_glucose", "cv_pct", "below_54_pct",
    "below_70_pct", "above_180_pct", "nocturnal_below_70_pct",
)


def _wmean(rows: list[tuple[float, dict]], field: str) -> float | None:
    num = sum(w * v[field] for w, v in rows if v.get(field) is not None)
    den = sum(w for w, v in rows if v.get(field) is not None)
    return round(num / den, 1) if den else None


def _tir_direction(rows: list[tuple[float, dict, str]]) -> float | None:
    if len(rows) < 2:
        return None
    ordered = sorted(rows, key=lambda t: t[2])
    mid = len(ordered) // 2
    older = _wmean([(w, v) for w, v, _ in ordered[:mid]], "tir_pct")
    newer = _wmean([(w, v) for w, v, _ in ordered[mid:]], "tir_pct")
    if older is None or newer is None:
        return None
    return round(newer - older, 1)


def aggregate_daily_cgm(reports: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Reading-weighted mean of daily CGM reports into one window summary,
    plus a week-over-week TIR direction (newer half vs older half)."""
    rows = []
    sensor_sum = 0.0
    sensor_w = 0
    for r in reports or []:
        md = r.get("metadata") or {}
        weight = md.get("total_readings") or 0
        if weight > 0:
            date = (md.get("date_range") or {}).get("start") or ""
            rows.append((weight, cgm_inputs(r), date))
            sa = md.get("sensor_active_percent")
            if sa is not None:
                sensor_sum += weight * sa
                sensor_w += weight
    if not rows:
        return {}

    plain = [(w, v) for w, v, _ in rows]
    out: dict[str, Any] = {field: _wmean(plain, field) for field in _AGG_FIELDS}
    if out.get("avg_glucose") is not None:
        out["gmi"] = round(3.31 + 0.02392 * out["avg_glucose"], 1)
    out["tir_delta"] = _tir_direction(rows)
    hypo = [v["hypo_events"] for _, v, _ in rows if v.get("hypo_events") is not None]
    out["hypo_events"] = sum(hypo) if hypo else None
    out["reading_count"] = sum(w for w, _, _ in rows)
    out["days_of_data"] = len(rows)
    out["sensor_active_pct"] = round(sensor_sum / sensor_w, 1) if sensor_w else None
    return out


def fitness_inputs(reports: list[dict[str, Any]] | None) -> dict[str, Any]:
    rows = []
    for r in reports or []:
        steps = r.get("steps")
        if steps is not None:
            date = ((r.get("metadata") or {}).get("date_range") or {}).get("start") or ""
            rows.append((steps, date))
    if not rows:
        return {}

    out: dict[str, Any] = {"avg_steps": round(sum(s for s, _ in rows) / len(rows))}
    if len(rows) >= 4:
        ordered = sorted(rows, key=lambda t: t[1])
        mid = len(ordered) // 2
        older = round(sum(s for s, _ in ordered[:mid]) / mid)
        newer = round(sum(s for s, _ in ordered[mid:]) / (len(ordered) - mid))
        if older >= 500 and newer < older * 0.5:
            out["activity_dropping"] = True
            out["activity_note"] = f"steps {older:,}→{newer:,}"
    return out


def sleep_inputs(reports: list[dict[str, Any]] | None) -> dict[str, Any]:
    mins = [
        d for r in (reports or [])
        if (d := ((r.get("duration") or {}).get("total_duration")))
    ]
    if not mins:
        return {}
    return {"avg_sleep_hours": round(sum(mins) / len(mins) / 60, 1)}


def vitals_inputs(latest_vitals: list[dict[str, Any]] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for row in latest_vitals or []:
        vt = (row.get("type") or "").lower()
        val = row.get("value")
        if val is None:
            continue
        if vt in ("a1c", "hba1c"):
            out["a1c"] = val
        elif vt in ("fasting_glucose", "fbs"):
            out["fasting_glucose"] = val
    return out


def smbg_inputs(readings: list[Any] | None) -> dict[str, Any]:
    vals = []
    for r in readings or []:
        v = getattr(r, "glucose_level", None)
        if v is None and isinstance(r, dict):
            v = r.get("glucose_level")
        if isinstance(v, (int, float)):
            vals.append(v)
    if not vals:
        return {}
    return {"smbg_avg": round(sum(vals) / len(vals))}


def weight_inputs(readings: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Net weight change (kg) over the window: latest reading minus the oldest."""
    pts = [
        (str(r.get("time")), r["value"])
        for r in (readings or [])
        if r.get("value") is not None
    ]
    if len(pts) < 2:
        return {}
    pts.sort(key=lambda p: p[0])
    return {"weight_delta_kg": round(pts[-1][1] - pts[0][1], 1)}
