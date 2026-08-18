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
    for r in reports or []:
        weight = ((r.get("metadata") or {}).get("total_readings")) or 0
        if weight > 0:
            date = ((r.get("metadata") or {}).get("date_range") or {}).get("start") or ""
            rows.append((weight, cgm_inputs(r), date))
    if not rows:
        return {}

    plain = [(w, v) for w, v, _ in rows]
    out: dict[str, Any] = {field: _wmean(plain, field) for field in _AGG_FIELDS}
    if out.get("avg_glucose") is not None:
        out["gmi"] = round(3.31 + 0.02392 * out["avg_glucose"], 1)
    out["tir_delta"] = _tir_direction(rows)
    out["reading_count"] = sum(w for w, _, _ in rows)
    return out


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


def smbg_inputs(readings: list[dict[str, Any]] | None) -> dict[str, Any]:
    vals = [
        r["value"] for r in (readings or [])
        if isinstance(r.get("value"), (int, float))
    ]
    if not vals:
        return {}
    return {"smbg_avg": round(sum(vals) / len(vals))}
