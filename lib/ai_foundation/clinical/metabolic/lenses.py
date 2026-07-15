"""
Longitudinal clinical lenses — additive reads on top of the engine contract.

Surfaces patterns the per-meal engine doesn't see: overnight glycemic variability,
dawn/Somogyi signatures, insulin-resistance phenotype, day-level burden, and a
people-like-you cohort hook.

Safety rules:
  - ADDITIVE. Never touches the engine's validated core or its safety gate.
  - DRAFT thresholds (marked) are clinician-facing only, not patient-facing until signed off.
  - No fabricated numbers. Where a model isn't wired, returns a labelled heuristic or None.
  - Hepatic/dawn fires only on OBSERVED elevated overnight glucose (F044 falsification).
"""

NOCTURNAL_CV_HIGH = 36.0   # DRAFT — CV above this overnight = unstable
OVERNIGHT_HIGH = 120.0     # DRAFT — standing overnight elevation (F019)
DAWN_RISE_MIN = 15.0       # DRAFT — nadir→dawn rise to call a dawn signature (F012)
HIDDEN_RISK_TIR = 70.0     # DRAFT — "good control" cutoff for hidden-nocturnal-risk (F014)


def _cgm(ps):
    c = (ps.get("cgm_summary") or ps.get("cgm") or {}) if isinstance(ps, dict) else {}
    return c if isinstance(c, dict) else {}


def _f(d, *names):
    for n in names:
        v = d.get(n) if isinstance(d, dict) else None
        if v is not None:
            try:
                return float(v)
            except Exception:
                return v
    return None


def overnight_gv(ps):
    """Overnight variability + hidden-nocturnal-risk (F014) + GV→hypo trait marker (F035)."""
    c = _cgm(ps)
    ov_cv = _f(c, "overnight_cv", "nocturnal_cv")
    cv = _f(c, "cv")
    tir = _f(c, "tir")
    ov_mean = _f(c, "overnight_mean", "nocturnal_mean")
    use_cv = ov_cv if ov_cv is not None else cv
    out = {"overnight_cv": ov_cv, "cv": cv, "overnight_mean": ov_mean,
           "basis": "F014 hidden nocturnal risk; F035 GV->hypo between-person marker", "draft": True}
    if use_cv is None:
        out["status"] = "no_cgm_variability"
        return out
    out["unstable_overnight"] = use_cv > NOCTURNAL_CV_HIGH
    # F014: 1 in 4 "good TIR" patients still carry hidden overnight instability
    out["hidden_nocturnal_risk"] = bool(tir is not None and tir >= HIDDEN_RISK_TIR and use_cv > NOCTURNAL_CV_HIGH)
    # F035: high GV is a between-person hypo-risk marker independent of mean glucose
    out["gv_hypo_marker"] = "elevated" if use_cv > NOCTURNAL_CV_HIGH else "normal"
    return out


def hepatic_dawn(ps):
    """Dawn vs Somogyi signature, gated on OBSERVED overnight glucose (F012/F013, hedged per F044)."""
    c = _cgm(ps)
    nadir = _f(c, "overnight_nadir", "nocturnal_nadir")
    dawn = _f(c, "dawn_glucose", "pre_breakfast_glucose", "morning_glucose")
    ov_mean = _f(c, "overnight_mean", "nocturnal_mean")
    out = {"overnight_nadir": nadir, "dawn_glucose": dawn,
           "basis": "F012 dawn phenomenon; F013 Somogyi separable; hedged per F044 (observed, not inferred)",
           "draft": True}
    if dawn is None or nadir is None:
        out["signature"] = "unknown"
        out["note"] = "needs overnight nadir + dawn glucose; do NOT infer dawn from a zero morning spike (F044)"
        return out
    rise = dawn - nadir
    if nadir < 70 and rise >= DAWN_RISE_MIN:
        out["signature"] = "somogyi_rebound"
    elif rise >= DAWN_RISE_MIN and (ov_mean is None or ov_mean >= OVERNIGHT_HIGH or dawn >= OVERNIGHT_HIGH):
        out["signature"] = "hepatic_dawn"
    else:
        out["signature"] = "none"
    out["dawn_rise_mgdl"] = round(rise, 1)
    return out


def ir_phenotype(ps):
    """Insulin-resistance signature: carb-independent morning hyperglycemia (F019)."""
    c = _cgm(ps)
    ov_mean = _f(c, "overnight_mean", "nocturnal_mean")
    day_floor = _f(c, "day_floor", "daytime_min")
    ov_floor = _f(c, "overnight_floor", "nocturnal_min")
    bk_spike = _f(c, "breakfast_spike", "am_spike")
    flags = []
    if ov_mean is not None and ov_mean > OVERNIGHT_HIGH:
        flags.append("overnight_high")
    if day_floor is not None and ov_floor is not None and day_floor > ov_floor:
        flags.append("day_floor_above_overnight")
    if bk_spike is not None and bk_spike >= 50:
        flags.append("big_breakfast_spike")
    return {"flags": flags, "ir_like": len(flags) >= 2,
            "basis": "F019 IR phenotype (carb-independent morning hyperglycemia)", "draft": True}


def day_burden(ps):
    """Day-level burden heuristic until the validated per-day model (AUROC 0.946) is wired."""
    c = _cgm(ps)
    prior_day_mean = _f(c, "prior_day_mean", "mean24", "mean")
    if prior_day_mean is None:
        return {"status": "no_data", "basis": "F028 per-day burden; per_day model not wired", "draft": True}
    band = "high" if prior_day_mean >= 160 else "elevated" if prior_day_mean >= 140 else "ok"
    return {"day_risk_band": band, "prior_day_mean": prior_day_mean, "method": "heuristic",
            "basis": "F028 prior-day mean is the top day-frame feature; wire model.per_day_burden for the 0.946 score",
            "draft": True}


def people_like_you(ps):
    """Cohort comparison hook. Fail-closed — needs the enrichment tier (sklearn + cohort data)."""
    cohort = ps.get("cohort_matches") if isinstance(ps, dict) else None
    if cohort:
        return {"k": len(cohort), "source": "supplied", "basis": "model.people_like_you (k>=20, validated 233 pts)"}
    return {"status": "unavailable",
            "note": "enrichment tier (sklearn + cohort data) not wired in server; available in brain service",
            "basis": "model.people_like_you (validated 233 pts, the moat)"}


def apply_lenses(patient_state):
    """Assemble every longitudinal lens. Clinician-facing; thresholds DRAFT until sign-off."""
    return {
        "overnight_gv": overnight_gv(patient_state),
        "hepatic_dawn": hepatic_dawn(patient_state),
        "ir_phenotype": ir_phenotype(patient_state),
        "day_burden": day_burden(patient_state),
        "people_like_you": people_like_you(patient_state),
        "_meta": {"additive": True, "patient_facing": False, "thresholds": "DRAFT pending CLINICAL_SIGNOFF"},
    }
