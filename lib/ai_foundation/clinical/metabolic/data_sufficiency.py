"""
Data-sufficiency + cold-start logic for the metabolic clinical module.

Three jobs:
  1. The personal-model BUILD GRAPH. Given a user's own paired meal+CGM events, return the expected
     accuracy (MAE, within-band) from the validated learning curve, the user's tier, and how many
     more datapoints (and days) to the next tier. Source: RESEARCH_MASTER/LEARNING_CURVE.md.
  2. PER-SOURCE quantitative requirements. Each input has its own "how much is enough" threshold, not a
     connected yes/no. CGM is measured in days of >=70% wear (not a boolean): the international consensus
     is 14 days at >=70% wear to estimate TIR/GMI/CV (Battelino et al. 2019, Diabetes Care). Each source
     reports have / need / unlocked and a quantitative nudge ("you have 5 of 14 CGM days, 9 to unlock TIR").
  3. The LOW-DATA path. When data is thin, do NOT fake a personal number. Route to EDUCATIONAL, ground any
     number in the People Like You cohort (privacy floor 20), and nudge the highest-leverage missing data.

Pure Python stdlib, stateless, no PHI. Mirrors the engine _confidence / SUGGEST-gate thresholds.
"""

# Validated learning curve: own paired meals (k) -> peak-rise MAE (mg/dL) and within +/-35 band.
# RESEARCH_MASTER/LEARNING_CURVE.md (15 patients >=80 meals). k=0 = population (real_model_report MAE 28.45).
LEARNING_CURVE = [
    (0, 28.5, 0.62), (5, 24.5, 0.75), (10, 25.7, 0.72),
    (20, 24.7, 0.79), (30, 23.9, 0.76), (40, 22.5, 0.80), (60, 19.6, 0.83),
]

# Meal-model tiers (own paired meals). cold_start < 8 mirrors the SUGGEST gate; 30 and 60 are the curve plateau.
TIERS = [
    ("cold_start", 0, 8, "EDUCATIONAL"),
    ("emerging", 8, 30, "NUMERIC_WIDE"),
    ("personal", 30, 60, "NUMERIC"),
    ("rich", 60, 10**9, "NUMERIC_TIGHT"),
]

# Per-source quantitative requirements. `min_unlock` in `unit` units turns the capability on; `ideal` is full
# confidence. `leverage` ranks the nudge order. CGM is days-of-wear, not a boolean. Thresholds are grounded:
#   cgm 14d/70% wear = international consensus for valid TIR/GMI/CV; paired meals = the learning curve;
#   bca >=2 / labs >=2 = needed for a trend; wearables ~14d to overlap the CGM window.
# confidence: HIGH = external clinical standard or definitional; MODERATE = derived from our own (small) data;
# DRAFT = placeholder set by default, NOT yet derived/tested. Treat DRAFT numbers as provisional until a
# derivation test (see basis) is run. This honors the evidence-design gate: no number ships as fact without provenance.
SOURCE_REQUIREMENTS = {
    "cgm":         {"unit": "days at >=70% wear", "min_unlock": 14, "ideal": 14, "leverage": 10,
                    "unlocks": "valid TIR, GMI, CV, dawn/nocturnal risk", "partial": "3-13 days gives provisional patterns",
                    "confidence": "HIGH", "basis": "international consensus 14d/>=70% wear (Battelino 2019, Diabetes Care; ADA SoC)"},
    "food_photos": {"unit": "meals logged paired with CGM", "min_unlock": 8, "ideal": 30, "leverage": 9,
                    "unlocks": "personal spike attribution (carb/fiber/protein/fat -> rise)", "partial": "each meal sharpens the personal model",
                    "confidence": "MODERATE", "basis": "our learning curve, RESEARCH_MASTER/LEARNING_CURVE.md (n=15 patients); plateau 8/30/60"},
    "labs":        {"unit": "A1c / insulin results", "min_unlock": 1, "ideal": 3, "leverage": 7,
                    "unlocks": "metabolic risk cross-section", "partial": ">=2 spaced >=90d unlock trajectory + EARLY_DRIFT",
                    "confidence": "HIGH", "basis": "A1c reflects ~3-month (RBC ~120d) glycemia, so trend points must be >=90d apart (ADA: A1c q3 months); >=3 for a reliable trend"},
    "meds":        {"unit": "current list (+ dose timestamps)", "min_unlock": 1, "ideal": 1, "leverage": 7,
                    "unlocks": "medication-vs-meal context", "partial": "dose timestamps unlock PK/PD timing",
                    "confidence": "HIGH", "basis": "definitional: 1 = the current list exists; PK/PD timing needs timestamped dose events"},
    "bca":         {"unit": "body-composition scans", "min_unlock": 1, "ideal": 2, "leverage": 6,
                    "unlocks": "BMIQ score + visceral/sarcopenic flags", "partial": ">=2 over ~90d unlock loss-quality trend",
                    "confidence": "MODERATE", "basis": "1 scan validated on 706-cohort (BMIQ); serial from C1 longitudinal (127 patients, median 196d)"},
    "fitness":     {"unit": "days of wearable overlapping CGM", "min_unlock": 14, "ideal": 14, "leverage": 5,
                    "unlocks": "personalized post-meal-walk lever + activity context", "partial": "more days sharpen the activity signal",
                    "confidence": "DRAFT", "basis": "PLACEHOLDER: matched-to-CGM default. Real requirement is paired post-meal move-vs-not events; steps were NULL as a predictor, so this is a lever-readiness threshold to DERIVE, not days"},
    "sleep":       {"unit": "nights of wearable overlapping CGM", "min_unlock": 14, "ideal": 14, "leverage": 5,
                    "unlocks": "sleep-to-glucose + overnight/dawn context", "partial": "more nights sharpen the sleep signal",
                    "confidence": "DRAFT", "basis": "PLACEHOLDER: matched-to-CGM default; the sleep-CGM link itself is N=1 to N=2, unproven (OPEN_QUESTIONS #16)"},
    "fundus":      {"unit": "retinal images", "min_unlock": 1, "ideal": 2, "leverage": 4,
                    "unlocks": "retinopathy screening linked to glucose control", "partial": "serial images track progression",
                    "confidence": "HIGH", "basis": "one gradable fundus image screens for DR (standard); serial for progression"},
    "vitals":      {"unit": "BP/HR readings", "min_unlock": 3, "ideal": 3, "leverage": 3,
                    "unlocks": "cardiometabolic context", "partial": "ongoing readings refine the risk picture",
                    "confidence": "DRAFT", "basis": "PLACEHOLDER: 3 is arbitrary; not derived"},
    "mood":        {"unit": "logs", "min_unlock": 7, "ideal": 14, "leverage": 2,
                    "unlocks": "stress-to-glucose context + adherence", "partial": "more logs sharpen the correlation",
                    "confidence": "DRAFT", "basis": "PLACEHOLDER: 7/14 arbitrary; needs enough paired mood-glucose events to correlate"},
    "symptoms":    {"unit": "logs", "min_unlock": 7, "ideal": 14, "leverage": 2,
                    "unlocks": "hypo/hyper symptom correlation + safety context", "partial": "more logs sharpen the correlation",
                    "confidence": "DRAFT", "basis": "PLACEHOLDER: 7/14 arbitrary; needs paired symptom-glucose events"},
}

# Minimum CGM days to allow ANY provisional glucose number (below this, education only even with meals logged).
CGM_MIN_PROVISIONAL_DAYS = 3


def _interp(x, table):
    if x <= table[0][0]:
        return table[0][1], table[0][2]
    if x >= table[-1][0]:
        return table[-1][1], table[-1][2]
    for i in range(1, len(table)):
        k0, m0, b0 = table[i - 1]; k1, m1, b1 = table[i]
        if x <= k1:
            f = (x - k0) / (k1 - k0)
            return round(m0 + f * (m1 - m0), 1), round(b0 + f * (b1 - b0), 3)
    return table[-1][1], table[-1][2]


def expected_personal_accuracy(own_meals):
    mae, band = _interp(own_meals, LEARNING_CURVE)
    return {"own_meals": own_meals, "expected_mae_mgdl": mae, "within_band_35": band,
            "basis": "population" if own_meals < 5 else "personal"}


def tier_for(own_meals):
    for name, lo, hi, mode in TIERS:
        if lo <= own_meals < hi:
            return name, mode
    return TIERS[0][0], TIERS[0][3]


def next_tier_target(own_meals, meals_per_day=3):
    for name, lo, hi, _mode in TIERS:
        if own_meals < lo:
            need = lo - own_meals
            return {"next_tier": name, "meals_needed": need, "approx_days": round(need / meals_per_day, 1)}
    return {"next_tier": None, "meals_needed": 0, "approx_days": 0}


def build_graph(max_k=72, step=6):
    out = []
    for k in range(0, max_k + 1, step):
        acc = expected_personal_accuracy(k)
        out.append({"own_meals": k, "expected_mae_mgdl": acc["expected_mae_mgdl"],
                    "within_band_35": acc["within_band_35"], "tier": tier_for(k)[0]})
    return out


def source_readiness(quantities):
    """Per-source: have vs need, unlocked or not, percent, and what it unlocks. `quantities` maps
    source -> a number in that source's unit (e.g. {'cgm': 5, 'food_photos': 12, 'bca': 1})."""
    rows = []
    for src, req in SOURCE_REQUIREMENTS.items():
        have = float(quantities.get(src, 0) or 0)
        need = req["min_unlock"]
        unlocked = have >= need
        rows.append({
            "source": src, "have": have, "need": need, "unit": req["unit"],
            "unlocked": unlocked, "pct": round(min(1.0, have / need), 2) if need else 1.0,
            "ideal": req["ideal"], "unlocks": req["unlocks"], "leverage": req["leverage"],
            "partial_note": req["partial"], "confidence": req["confidence"],
            # gating = this source's threshold is evidence-backed enough to gate a number.
            # DRAFT sources are feedback/nudge only and must NEVER gate or weaken a number.
            "gating": req["confidence"] != "DRAFT",
        })
    return rows


def assess_readiness(signals):
    """
    signals: {
      'paired_meals': int,                 # own meal+CGM events -> the personal spike model (build graph)
      'quantities': {source: number},      # how much of each source exists, in that source's unit
      'cohort_n': int|None                 # People Like You matched cohort size (privacy floor 20)
    }
    Returns the full data-sufficiency block: build graph point + meal tier, CGM coverage gate,
    per-source readiness, the cohort fallback decision, the overall output mode, and a ranked
    QUANTITATIVE nudge ("you have X of Y, N more to unlock Z").
    """
    q = signals.get("quantities", {}) or {}
    paired = int(signals.get("paired_meals", q.get("food_photos", 0)) or 0)
    cohort_n = signals.get("cohort_n")
    cgm_days = float(q.get("cgm", 0) or 0)

    meal_tier, meal_mode = tier_for(paired)
    acc = expected_personal_accuracy(paired)
    nxt = next_tier_target(paired)
    sources = source_readiness(q)

    # CGM coverage gate (separate from the meal count): glucose metrics need enough wear.
    cgm_full = cgm_days >= SOURCE_REQUIREMENTS["cgm"]["min_unlock"]      # 14d
    cgm_provisional = cgm_days >= CGM_MIN_PROVISIONAL_DAYS               # 3d

    # Overall output mode: gated by BOTH the meal count AND CGM coverage. Personal numbers need both.
    if paired < 8 or not cgm_provisional:
        overall_mode = "EDUCATIONAL"
    elif not cgm_full:
        overall_mode = "NUMERIC_WIDE"          # have meals + some CGM, but under the 14-day metric standard
    else:
        overall_mode = meal_mode               # full CGM coverage -> the meal tier decides the tightness

    cohort_ok = isinstance(cohort_n, int) and cohort_n >= 20
    if overall_mode == "EDUCATIONAL":
        number_source = "people_like_you" if cohort_ok else "education_only"
    else:
        number_source = "personal"

    # Ranked quantitative nudge: unmet sources, highest leverage first, with the exact shortfall.
    unmet = [s for s in sources if not s["unlocked"]]
    unmet.sort(key=lambda s: -s["leverage"])
    nudges = [{"connect": s["source"],
               "have": s["have"], "need": s["need"], "unit": s["unit"],
               "remaining": round(s["need"] - s["have"], 1),
               "to_unlock": s["unlocks"],
               "confidence": s["confidence"],
               "gating": s["gating"]} for s in unmet[:3]]

    return {
        "meal_model": {"tier": meal_tier, "expected_accuracy": acc, "next_tier": nxt},
        "cgm_coverage": {"have_days": cgm_days, "need_days": SOURCE_REQUIREMENTS["cgm"]["min_unlock"],
                         "provisional": cgm_provisional, "full": cgm_full,
                         "standard": "14 days at >=70% wear (Battelino 2019)"},
        "sources": sources,
        "overall_output_mode": overall_mode,        # EDUCATIONAL | NUMERIC_WIDE | NUMERIC | NUMERIC_TIGHT
        "number_source": number_source,             # personal | people_like_you | education_only
        "cohort_fallback": cohort_ok,
        "nudge_to_share": nudges,
    }


if __name__ == "__main__":
    import json
    print("BUILD GRAPH (own_meals -> expected MAE, within-band, tier):")
    for p in build_graph():
        print("  k=%2d  MAE=%4.1f  band=%2.0f%%  tier=%s" % (p["own_meals"], p["expected_mae_mgdl"], p["within_band_35"]*100, p["tier"]))
    print("\nNEW USER (5 CGM days, 4 meals, no cohort):")
    print(json.dumps(assess_readiness({"paired_meals": 4, "quantities": {"cgm": 5, "food_photos": 4}, "cohort_n": None}), indent=2))
    print("\nESTABLISHED (16 CGM days, 35 meals, InBody+meds):")
    print(json.dumps(assess_readiness({"paired_meals": 35, "quantities": {"cgm": 16, "food_photos": 35, "bca": 2, "meds": 1, "labs": 2}, "cohort_n": 40})["overall_output_mode"], indent=2))
