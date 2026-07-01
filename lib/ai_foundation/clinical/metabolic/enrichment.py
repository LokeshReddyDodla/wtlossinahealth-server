#!/usr/bin/env python3
"""AiHealth Engine v3.1 upgrades — additive output enrichment (the Mukhtar gap fixes).

This wraps the EngineV2 output WITHOUT touching the validated core, so it is safe to
run in shadow and cannot break the spike model, the safety gate, or the attribution.
It implements the engineering gaps Mukhtar reported:

  Gap 1 (safety): if there is no live pre-meal glucose, raise safety_unchecked so the
                  renderer never implies a safety check happened. The 3-month/twin prior
                  personalizes the PREDICTION only; it NEVER feeds the real-time hypo gate.
  Gap 3 (peak):   emit peak_minutes — personal per-slot median when the patient has the
                  history (>=3 same-slot meals), else a composition heuristic.
  Gap 4 (cited):  surface the 2-3 most similar past meals as evidence.
  Gap 6 (cgm):    set has_cgm + a confidence tier; with no CGM, no personal number.
  No-live-data:   when pre is missing, fill a time-of-day twin prior from the 90-day AGP
                  (expected glucose at this hour), tagged as a prior, not a live reading.

Pure stdlib. Defensive: reads attribute-or-dict with several name fallbacks, never raises.
"""
from statistics import median

P1_SLOT_BASE = {"breakfast": 50, "lunch": 55, "dinner": 60, "snack": 45}  # heuristic peak-min base


def _get(obj, *names, default=None):
    for n in names:
        if isinstance(obj, dict) and n in obj and obj[n] is not None:
            return obj[n]
        if hasattr(obj, n) and getattr(obj, n) is not None:
            return getattr(obj, n)
    return default


def _slot(meal, hour=None):
    s = _get(meal, "meal_type", "slot")
    if s:
        return str(s).lower()
    h = hour if hour is not None else _get(meal, "hour", default=12)
    try:
        h = int(h)
    except Exception:
        h = 12
    return "breakfast" if h < 11 else "lunch" if h < 16 else "dinner" if h < 21 else "snack"


def _recent_meals(patient_state):
    rm = _get(patient_state, "recent_meals", "meals", "meal_history", default=[]) or []
    return rm if isinstance(rm, list) else []


def has_cgm(patient_state):
    """True if the patient has any CGM signal we can stand on."""
    cgm = _get(patient_state, "cgm_summary", "cgm", default=None)
    if cgm and (_get(cgm, "tir", "cv", "mean") is not None):
        return True
    if _get(patient_state, "cgm_readings", "cgm_series", default=None):
        return True
    return False


def peak_minutes(patient_state, meal):
    """Personal per-slot median time-to-peak (>=3 same-slot meals with a peak time), else heuristic.

    Returns (minutes, tier) where tier is 'personal' or 'heuristic'.
    """
    slot = _slot(meal)
    ttps = []
    for m in _recent_meals(patient_state):
        if _slot(m) != slot:
            continue
        t = _get(m, "time_to_peak", "ttp", "peak_minutes", "minutes_to_peak")
        if t is not None:
            try:
                ttps.append(float(t))
            except Exception:
                pass
    if len(ttps) >= 3:
        return int(round(median(ttps))), "personal"
    # composition heuristic: high fat -> later, high simple-carb / low fat -> earlier
    base = P1_SLOT_BASE.get(slot, 55)
    carb = _get(meal, "carbs", "carb", default=0) or 0
    fat = _get(meal, "fat", default=0) or 0
    fiber = _get(meal, "fiber", "fibre", default=0) or 0
    if fat and fat >= 20:
        base += 30
    if carb and carb >= 45 and (fat or 0) < 10 and (fiber or 0) < 4:
        base -= 15  # simple, fast carb
    return int(max(25, min(140, base))), "heuristic"


def evidence_meals(patient_state, meal, k=3):
    """Up to k most similar past meals by carb proximity within the same slot."""
    slot = _slot(meal)
    carb = _get(meal, "carbs", "carb", default=None)
    cands = []
    for m in _recent_meals(patient_state):
        if _slot(m) != slot:
            continue
        mc = _get(m, "carbs", "carb", default=None)
        peak = _get(m, "peak", "observed_peak", "glucose_peak")
        date = _get(m, "date", "dt", "logged_at", "timestamp")
        dist = abs((mc or 0) - (carb or 0)) if (mc is not None and carb is not None) else 999
        cands.append((dist, {"date": date, "observed_peak": peak, "carbs": mc,
                             "dish": _get(m, "dish", "name", "dishkey")}))
    cands.sort(key=lambda x: x[0])
    return [c[1] for c in cands[:k] if c[1]["observed_peak"] is not None or c[1]["date"] is not None]


def twin_pre_prior(patient_state, meal):
    """No-live-data fallback: expected glucose at THIS hour from the 90-day AGP.

    Returns {value, provenance, note} or None. This is a PRIOR for the prediction only;
    it must never be passed to the safety gate as if it were a live reading.
    """
    hour = _get(meal, "hour")
    agp = _get(patient_state, "agp_hourly", "agp", "tod_glucose", default=None)
    if agp and hour is not None:
        try:
            v = agp.get(str(int(hour))) if isinstance(agp, dict) else None
            if v is not None:
                return {"value": float(v), "provenance": "90d_prior", "note": "expected glucose at this hour, not a live reading"}
        except Exception:
            pass
    mean = _get(_get(patient_state, "cgm_summary", "cgm", default={}) or {}, "mean")
    if mean is not None:
        return {"value": float(mean), "provenance": "90d_mean", "note": "90-day mean, not a live reading or time-of-day prior"}
    return None


def confidence_tier(patient_state, live_pre):
    n = _get(patient_state, "n_meals_learned", default=None)
    cgm = has_cgm(patient_state)
    if not cgm:
        return "low_no_cgm"
    if live_pre is None:
        return "moderate_prior"  # personalized but no live reading
    if n is not None and n >= 20:
        return "high"
    if n is not None and n >= 6:
        return "moderate"
    return "cold_start"


def enrich(engine_out, patient_state, meal, live_pre=None):
    """Add the v3.1 fields to a copy of the engine's contract. Never mutates the core logic."""
    out = dict(engine_out) if isinstance(engine_out, dict) else {"engine_out": engine_out}
    up = {}
    # Gap 1: safety honesty when there is no live reading
    if live_pre is None:
        up["safety_unchecked"] = True
        up["safety_note"] = "No live glucose at meal time; hypo/very-high safety gate could not run. Prediction is from history only."
        prior = twin_pre_prior(patient_state, meal)
        if prior:
            up["pre_prior"] = prior  # for prediction only, tagged; NOT a safety input
    else:
        up["safety_unchecked"] = False
    # Gap 3
    pm, tier = peak_minutes(patient_state, meal)
    up["peak_minutes"] = pm
    up["peak_minutes_basis"] = tier
    # Gap 4
    up["evidence_meals"] = evidence_meals(patient_state, meal)
    # Gap 6
    up["has_cgm"] = has_cgm(patient_state)
    up["confidence_tier"] = confidence_tier(patient_state, live_pre)
    up["show_number_to_patient"] = bool(up["has_cgm"])  # app hides the number for non-CGM patients
    out["v31"] = up
    return out
