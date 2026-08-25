"""
Metabolic engine — deterministic clinical brain for glucose prediction, attribution, and coaching.

Emits a structured contract for LLM rendering. Does NOT author patient-facing prose.

Design rules:
  - Pure Python stdlib, stateless per patient.
  - Every number traces to a validated source (data/levers.json) or the patient's own data.
  - Zero hallucination: emit a SUGGEST only when meal-driven + confident + an evidence-backed lever exists;
    otherwise REINFORCE / FLAG_PHYSIOLOGY / STATE_FACTS. No forced advice.
  - Meal-vs-physiology attribution: decompose the rise; never blame a balanced plate for a physiology spike.

Two call modes:
  - assess(state, meal) with meal['observed_peak'] present  -> post-hoc / follow-up: full attribution.
  - assess(state, meal) without observed_peak               -> live (meal just logged): predicted rise.
"""
import json
import logging
import os

from .bmiq import BmiqScorer
from .util import num as _num, slot_index as slot

_HERE = os.path.dirname(os.path.abspath(__file__))
def _load(name, default):
    p = os.path.join(_HERE, "data", name)
    try:
        with open(p, "r", encoding="utf-8") as f: return json.load(f)
    except Exception:
        # Degraded clinical mode must be LOUD: with the default, the engine
        # runs with no levers / no spike model and nothing explains why.
        logging.getLogger(__name__).error("metabolic data file %s failed to load — running degraded", name, exc_info=True)
        return default

LEVERS_DATA = _load("levers.json", {"levers": {}, "circadian_breakfast_mgdl": 12.35})
PHENO = _load("phenotype_lookup.json", {})
SPIKE = _load("spike_model.json", None)   # validated GBM regressor (AUROC 0.787 sibling), exported as plain trees



class SpikeModel:
    """Validated GradientBoosting spike-rise regressor, run as a pure-stdlib tree-walk (no sklearn).
    Source: living_cohort/real_spike_model.pkl exported to data/spike_model.json. Predicts peak rise (mg/dL).
    Missing features fall back to the model's training-median defaults."""
    def __init__(self, m):
        # Forge P2: validate the export at load and FAIL CLOSED on anything malformed, so a bad model
        # never reaches predict() (where a cycle or bad index could hang). ok=False -> engine falls back
        # to the personal-slope path.
        self.ok = False
        if not (m and isinstance(m, dict) and m.get("trees")):
            return
        try:
            feats, defaults, trees = m["feats"], m["defaults"], m["trees"]
            init, lr = m["init"], m["lr"]
            if not feats or any(n not in defaults for n in feats):   # every feature needs a default
                return
            nf = len(feats)
            for t in trees:
                cl, cr, f, thr, val = t["cl"], t["cr"], t["f"], t["thr"], t["val"]
                L = len(cl)
                if L == 0 or not (len(cr) == len(f) == len(thr) == len(val) == L):
                    return                                           # arrays must be equal, non-empty
                for i in range(L):
                    if cl[i] != -1 and not (0 <= cl[i] < L): return  # child index in range or leaf
                    if cr[i] != -1 and not (0 <= cr[i] < L): return
                    if (cl[i] != -1 or cr[i] != -1) and not (0 <= f[i] < nf): return
            self.feats, self.init, self.lr, self.trees, self.defaults = feats, init, lr, trees, defaults
            self.ok = True
        except Exception:
            self.ok = False

    def predict(self, feat):
        if not self.ok:
            return None
        try:
            x = [(float(feat[n]) if feat.get(n) is not None else self.defaults[n]) for n in self.feats]
            total = 0.0
            for t in self.trees:
                cl, cr, f, thr, val = t["cl"], t["cr"], t["f"], t["thr"], t["val"]
                i = 0; steps = 0; lim = len(cl)
                while cl[i] != -1 or cr[i] != -1:
                    i = cl[i] if x[f[i]] <= thr[i] else cr[i]
                    steps += 1
                    if steps > lim:                                  # cycle guard: never hang
                        return None
                total += val[i]
            return self.init + self.lr * total
        except Exception:
            return None

# --- heuristic constants (PLACEHOLDER: pin to ADA / diabetes-India MNT before patient-facing, see levers.json) ---
CARB_TARGET = {0: 50, 1: 55, 2: 45, 3: 20}      # by slot
PRIOR_SLOPE = 0.40                               # population carb slope (mg/dL per g)
SHRINK_K = 10.0                                  # cold-start shrinkage strength
IN_RANGE_RISE = 40.0                             # below this = no problem rise
CIRCADIAN_BF = LEVERS_DATA.get("circadian_breakfast_mgdl", 12.35)  # q2

# GLP-1 detection is data-driven (data/glp1_medications.json) so brands — incl.
# India-specific ones — extend without a code change; the tuple here is only the
# fallback if the file fails to load.
_GLP1_FALLBACK = ("glp", "semaglutide", "liraglutide", "dulaglutide", "tirzepatide", "exenatide",
                  "ozempic", "rybelsus", "mounjaro", "wegovy", "trulicity", "victoza", "saxenda")
_GLP1 = tuple(n.lower() for n in _load("glp1_medications.json", {}).get("names") or _GLP1_FALLBACK)
def _glp1(prof):
    meds = prof.get("meds") or prof.get("medications") or []
    s = " ".join(str(m).lower() for m in meds) if isinstance(meds, (list, tuple)) else str(meds).lower()
    return any(k in s for k in _GLP1)


class MetabolicEngine:
    def __init__(self, levers=None, phenotype=None, prior_slope=PRIOR_SLOPE, bmiq_evidence=None):
        self.L = (levers or LEVERS_DATA).get("levers", {})
        self.circadian = (levers or LEVERS_DATA).get("circadian_breakfast_mgdl", CIRCADIAN_BF)
        self.restraint_cite = (levers or LEVERS_DATA).get("restraint_cite", "")
        self.dawn_guardrail = (levers or LEVERS_DATA).get("dawn_guardrail", "")
        self.PH = phenotype or PHENO
        self.prior_slope = prior_slope
        self.spike = SpikeModel(SPIKE)
        self._bmiq = BmiqScorer(evidence=bmiq_evidence)

    # ---- personal carb slope, shrunk to the population prior on thin history ----
    def personal_slope(self, history):
        xs = [h["carb"] for h in history if h.get("carb") is not None and h.get("peak") is not None]
        ys = [h["peak"] for h in history if h.get("carb") is not None and h.get("peak") is not None]
        n = len(xs)
        if n < 5:
            return self.prior_slope, n
        mx = sum(xs) / n; my = sum(ys) / n
        den = sum((x - mx) ** 2 for x in xs)
        raw = (sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den) if den > 0 else self.prior_slope
        raw = max(0.05, min(0.9, raw))
        w = n / (n + SHRINK_K)
        return w * raw + (1 - w) * self.prior_slope, n

    # ---- MMIQ tier from weekly CGM aggregates (v3 base rule) ----
    def tier(self, cgm):
        if not cgm or cgm.get("tir") is None or cgm.get("cv") is None:
            return None
        tir, cv = cgm["tir"], cgm["cv"]
        if tir >= 70 and cv <= 36: return "well_controlled"
        if tir >= 70 and cv > 36:  return "variable_controlled"
        if tir < 70 and cv <= 36:  return "consistent_elevated"
        return "high_risk_glucose"

    # ---- MMIQ driver decomposition: where this patient's dysglycemia comes from (Stage 3) ----
    def driver(self, cgm):
        """postprandial | nocturnal | basal | mixed | unknown, from CGM out-of-range share by window."""
        if not cgm:
            return "unknown"
        pp = cgm.get("postprandial_share"); nc = cgm.get("nocturnal_share")
        if pp is None or nc is None:
            return "unknown"
        basal = max(0.0, 1.0 - pp - nc)
        shares = {"postprandial": pp, "nocturnal": nc, "basal": basal}
        top = max(shares, key=shares.get)
        return top if shares[top] >= 0.45 else "mixed"

    # ---- safety gate (overrides everything; never authored away) ----
    def safety(self, pre, rise):
        flags = ["NO_MED_CHANGE"]
        override = None
        if pre is not None and pre < 80:
            flags.append("PRE_HYPO"); override = "PRE_HYPO"
        if pre is not None and pre > 250:
            flags.append("PRE_VERY_HIGH"); override = "PRE_VERY_HIGH"
        if rise is not None and rise > 120:
            flags.append("LARGE_EXCURSION_REVIEW")
        return flags, override

    def _balance(self, carb, prot, fib, cal, s):
        tgt = CARB_TARGET[s]
        carb_ok = carb <= tgt * 1.15
        fib_ok = (fib or 0) >= 4
        prot_ok = (prot or 0) >= 10
        cal_ok = (not cal) or cal <= 750
        balanced = carb_ok and fib_ok and (prot_ok or cal_ok)
        return dict(carb_ok=carb_ok, fiber_ok=fib_ok, protein_ok=prot_ok, cal_ok=cal_ok,
                    balanced=balanced, slot_target_g=tgt)

    def _pick_lever(self, bal, s, hour):
        cand = []
        if not bal["protein_ok"]: cand.append("protein_pair")
        if not bal["fiber_ok"]:   cand.append("fiber")
        cand.append("protein_first")
        if s == 2 and hour is not None and hour >= 20: cand.append("earlier_dinner")
        cand = [c for c in cand if c in self.L]
        if not cand: return None
        name = max(cand, key=lambda c: abs(self.L[c]["effect_mgdl"]))
        return dict(name=name, **self.L[name])

    @staticmethod
    def _confidence(n):
        return "high" if n >= 20 else "moderate" if n >= 6 else "cold-start"

    def _fact(self, carb, pre, rise, carb_comp, circ, pre_term, in_range, observed):
        # Forge P1: never show contradictory numbers. In LIVE mode there is no observed outcome, so we
        # present a PREDICTED band and a qualitative driver, not a decomposition of the GBM number that
        # would not sum. In OBSERVED mode we decompose the real rise and CAP each part so the shown parts
        # never exceed the rise (no "carbs explain +40" on a +30 peak), and baseline is explicit.
        prestr = ("%d" % pre) if pre is not None else "n/a"
        if observed is None:
            drv = ("mostly carbs" if carb_comp >= max(circ, pre_term) and carb_comp > 1 else
                   "morning circadian" if circ >= pre_term and circ > 0 else
                   "baseline glucose" if pre_term > 0 else "a small expected rise")
            return "%dg carb, pre %s. Predicted rise of about +%d mg/dL (driver: %s). Predicted, not yet observed." % (
                carb, prestr, round(max(0.0, rise)), drv)
        if rise < 15:
            f = "%dg carb, pre %s — no meaningful rise (observed %+d). This meal sat flat." % (carb, prestr, round(rise))
            if pre is not None and pre >= 180:
                f += " Pre-meal %d is high on its own — a baseline issue, not this plate." % pre
            return f
        c = max(0.0, min(carb_comp, rise))                  # cap parts to the observed rise
        z = max(0.0, min(circ, rise - c))
        b = max(0.0, min(pre_term, rise - c - z))
        rem = max(0.0, rise - c - z - b)
        base = "%dg carb, pre %s, observed rise +%d. Carbs explain about +%d" % (carb, prestr, round(rise), round(c))
        if z > 0: base += ", breakfast timing +%d" % round(z)
        if b > 0: base += ", baseline +%d" % round(b)
        base += "; the remaining +%d is other physiology." % round(rem)
        return base

    # ---- the one entry point: returns the engine->LLM contract ----
    def assess(self, patient_state, meal):
        history = patient_state.get("history", []) or []
        slope, n = self.personal_slope(history)
        carb = _num(meal.get("carb")) or 0.0
        pre = _num(meal.get("pre"))
        hour = _num(meal.get("hour"))
        prot = _num(meal.get("protein")) or 0.0
        fib = _num(meal.get("fiber")) or 0.0
        cal = _num(meal.get("cal")) or 0.0
        s = slot(hour if hour is not None else 12)
        circ = self.circadian if s == 0 else 0.0
        pre_term = max(0.0, 0.12 * ((pre - 100.0) if pre is not None else 0.0))
        carb_comp = max(0.0, slope * carb)
        predicted_slope = max(0.0, carb_comp + circ + pre_term)

        # patient-level context (read once)
        cgm = patient_state.get("cgm_summary")
        base = patient_state.get("base") or {}
        prof = patient_state.get("profile") or {}
        age = _num(prof.get("age")); bmi = _num(prof.get("bmi"))
        baseline_mean = _num((cgm or {}).get("mean")) or _num(base.get("overnight_mean"))
        glp1_flag = _glp1(prof)
        bmiq_block, weight_trend = self._bmiq.assess(patient_state, glp1_flag)

        # PREDICTION: validated GBM spike model (stdlib walker); personal-slope is the fallback
        feat = {"carb": carb, "protein": prot, "fat": _num(meal.get("fat")), "fiber": fib,
                "calories": (cal or None), "hour_of_day": hour, "pre_meal_glucose": pre,
                "pre_meal_slope_30min": _num(base.get("pre_slope_30min")),
                "user_baseline_mean": baseline_mean,
                "glp1_flag": 1.0 if glp1_flag else 0.0, "age": age, "bmi": bmi}
        model_pred = self.spike.predict(feat)
        pred_source = "model:gbm" if model_pred is not None else "personal_slope"
        predicted = model_pred if model_pred is not None else predicted_slope

        observed = _num(meal.get("observed_peak"))
        rise = observed if observed is not None else predicted
        residual = (observed - carb_comp - circ) if observed is not None else None
        meal_fraction = (max(0.0, min(1.0, carb_comp / rise)) if rise > 5 else None)

        bal = self._balance(carb, prot, fib, cal, s)
        pre_high = pre is not None and pre >= 140
        tier = patient_state.get("tier") or self.tier(cgm)
        ph = self.PH.get(tier, {}) if tier else {}

        # CGM-level signals (validated as dominant over meal macros — see aihealth-validation-state ladder)
        cgm_driver = self.driver(cgm)                      # MMIQ driver decomposition (B1)
        recent_cv = _num(base.get("recent_cv"))
        recent_mean = baseline_mean
        recent_unstable = (recent_cv is not None and recent_cv > 36) or (recent_mean is not None and recent_mean >= 160)

        # EARLY_DRIFT age-relative lens (memory: brain was diabetic-calibrated, blind to lean-young pre-DM)
        tir = (cgm or {}).get("tir")
        # pre-DM band = GMI 5.7-6.4 ~ mean 100-127; above that is diabetic range, not "early drift"
        early_drift = bool(cgm and tir is not None and tir >= 85 and recent_mean is not None
                           and 100 <= recent_mean < 127 and tier == "well_controlled")
        early_drift_young_lean = early_drift and ((age is not None and age <= 30) or (bmi is not None and bmi < 25))

        flags, override = self.safety(pre, rise)

        # ---- attribution (meal-level) ----
        in_range = rise < IN_RANGE_RISE
        physiology = None; phys_cite = None
        if n < 5:
            attribution = "INSUFFICIENT_HISTORY"
        elif in_range:
            attribution = "IN_RANGE"
        elif observed is not None and bal["balanced"] and meal_fraction is not None and meal_fraction < 0.45:
            attribution = "PHYSIOLOGY_DRIVEN"
        elif meal_fraction is not None and meal_fraction >= 0.6 and not bal["balanced"]:
            attribution = "MEAL_DRIVEN"
        elif observed is not None and pre_high and residual is not None and residual > 25:
            attribution = "PHYSIOLOGY_DRIVEN"
        else:
            attribution = "MIXED"

        # ---- CGM driver + recent-state cross-check (resolves the ambiguous case the way the data says) ----
        driver_consistent = None
        if attribution == "MIXED":
            if cgm_driver in ("nocturnal", "basal") or recent_unstable:
                attribution = "PHYSIOLOGY_DRIVEN"
                physiology = ("rise aligns with this patient's %s-dominant CGM pattern / unstable recent days, not the meal"
                              % (cgm_driver if cgm_driver not in ("unknown", "mixed") else "non-meal"))
                phys_cite = "MMIQ driver-decomposition (B1) + recent-state ladder (mean24/cv24 dominate spike variance; macros alone ~0)"
            elif cgm_driver == "postprandial" and not bal["balanced"] and meal_fraction is not None and meal_fraction >= 0.5:
                attribution = "MEAL_DRIVEN"
        if cgm_driver != "unknown":
            driver_consistent = ((attribution == "MEAL_DRIVEN" and cgm_driver == "postprandial")
                                 or (attribution == "PHYSIOLOGY_DRIVEN" and cgm_driver in ("nocturnal", "basal")))

        if attribution == "PHYSIOLOGY_DRIVEN" and physiology is None:
            if s == 0:
                physiology = "morning surge — consistent with a dawn-window endogenous rise, not this meal"
                phys_cite = self.dawn_guardrail
            elif pre_high:
                physiology = "started elevated before eating (pre %s)" % (("%d" % pre) if pre is not None else "n/a")
                phys_cite = "baseline hyperglycemia"
            else:
                physiology = "rise not explained by this meal's carbs"
                phys_cite = self.restraint_cite

        # ---- output-mode gate (zero hallucination) ----
        lever = None
        if override in ("PRE_HYPO", "PRE_VERY_HIGH"):
            mode = "SAFETY"
        elif attribution == "INSUFFICIENT_HISTORY":
            mode = "STATE_FACTS"
        elif attribution == "IN_RANGE":
            if pre is not None and pre >= 180:
                mode = "FLAG_PHYSIOLOGY"
                physiology = "baseline glucose already high (pre %d) — the meal did not cause it" % pre
                phys_cite = "standing hyperglycemia"
            elif bal["balanced"]:
                mode = "REINFORCE"
            else:
                mode = "STATE_FACTS"
        elif attribution == "PHYSIOLOGY_DRIVEN":
            mode = "FLAG_PHYSIOLOGY"
        elif attribution == "MEAL_DRIVEN" and n >= 8:
            lever = self._pick_lever(bal, s, hour)
            # Forge P2: a SUGGEST must carry a CITED lever, by construction. Uncited -> no suggestion.
            if lever and lever.get("cite"):
                mode = "SUGGEST"
            else:
                mode = "STATE_FACTS"; lever = None
        else:
            mode = "STATE_FACTS"

        # Cross-axis safety lock (Forge P0, 2026-06-18): a root SAFETY override (pre-meal hypo or
        # very-high glucose) must pre-empt ALL coaching in the contract, including the nested obesity
        # (BMIQ) axis. Without this, a hypo/very-high meal could still surface a BMIQ SUGGEST + lever.
        # Strictly downside-protective: it only ever makes the BMIQ axis more conservative.
        if mode == "SAFETY" and isinstance(bmiq_block, dict):
            bmiq_block["output_mode"] = "SAFETY_HOLD"
            bmiq_block["lever"] = None
            bmiq_block["safety_hold_reason"] = override

        # Referral (policy: suggestions are cautious and point to the right team; the engine never changes a
        # medication or dose). A diet one-move reinforces with the diet team; physiology, safety, and clinical
        # (BMIQ) flags route to the care team / doctor.
        referral = "diet_team" if mode == "SUGGEST" else None
        if mode in ("FLAG_PHYSIOLOGY", "SAFETY"):
            referral = "care_team"
        if isinstance(bmiq_block, dict) and bmiq_block.get("output_mode") == "FLAG":
            referral = "care_team"

        return {
            "prediction": {
                "rise_mgdl": round(rise, 1),
                "predicted_mgdl": round(predicted, 1),
                "observed_mgdl": (round(observed, 1) if observed is not None else None),
                "source": pred_source,                 # model:gbm (validated 0.787-sibling) or personal_slope fallback
                "confidence": self._confidence(n),
                "n_meals_learned": n,
                "personal_slope": round(slope, 3),
            },
            "attribution": {
                "label": attribution,
                "carb_component_mgdl": round(carb_comp, 1),
                "circadian_mgdl": round(circ, 1),
                "residual_mgdl": (round(residual, 1) if residual is not None else None),
                "pre_term_mgdl": round(pre_term, 1),       # baseline contribution, exposed (Forge P1)
                "meal_fraction": (round(meal_fraction, 2) if meal_fraction is not None else None),
                "cgm_driver": cgm_driver,                 # MMIQ driver decomposition: postprandial|nocturnal|basal|mixed
                "driver_consistent": driver_consistent,   # does this meal call agree with the patient's overall driver?
                "recent_state": {"recent_cv": recent_cv, "recent_mean": recent_mean, "unstable": recent_unstable},
                "physiology_signal": physiology,
                "physiology_evidence": phys_cite,
            },
            "patient_flags": {
                "early_drift": early_drift,               # lean/young upstream pre-DM lens (memory: EARLY_DRIFT)
                "early_drift_young_lean": early_drift_young_lean,
            },
            "plate": bal,
            "lever": lever,                      # None unless mode == SUGGEST
            "phenotype": {
                "tier": tier,
                "agent_tone": ph.get("agent_tone"),
                "clinical_note": ph.get("clinical_note"),
                "escalation_threshold": ph.get("escalation_threshold"),
            },
            "output_mode": mode,                 # SUGGEST | REINFORCE | FLAG_PHYSIOLOGY | STATE_FACTS | SAFETY
            "referral": referral,                # diet_team | care_team | None (suggestions are cautious + routed)
            "safety_flags": flags,
            "bmiq": bmiq_block,
            "weight_trend": weight_trend,
            "fact": self._fact(carb, pre, rise, carb_comp, circ, pre_term, in_range, observed),
            "restraint_cite": self.restraint_cite,
        }


if __name__ == "__main__":
    eng = MetabolicEngine()
    hist = [dict(carb=c, protein=10, fiber=5, cal=500, pre=110, hour=13, peak=0.45 * c + 4) for c in (40, 55, 60, 70, 45, 50, 65, 38)]
    demo = [
        ("balanced in-range",  dict(carb=45, protein=18, fiber=6, cal=520, pre=108, hour=13, observed_peak=22)),
        ("carb-heavy lunch",   dict(carb=95, protein=8, fiber=2, cal=640, pre=120, hour=13, observed_peak=58)),
        ("balanced morning still spikes", dict(carb=40, protein=14, fiber=6, cal=420, pre=150, hour=8, observed_peak=70)),
        ("standing high, flat meal", dict(carb=55, protein=12, fiber=5, cal=500, pre=205, hour=20, observed_peak=-2)),
        ("hypo before meal",   dict(carb=40, protein=8, fiber=4, cal=360, pre=74, hour=13, observed_peak=20)),
    ]
    pp_state = {"history": hist, "cgm_summary": {"tir": 72, "cv": 30, "postprandial_share": 0.62, "nocturnal_share": 0.18}}
    noct_state = {"history": hist, "cgm_summary": {"tir": 66, "cv": 38, "postprandial_share": 0.18, "nocturnal_share": 0.6},
                  "base": {"recent_cv": 41, "overnight_mean": 168}}
    demo = demo + [("mid meal, but patient is nocturnal-driven",
                    dict(carb=62, protein=12, fiber=4, cal=560, pre=130, hour=13, observed_peak=46), noct_state)]
    for item in demo:
        label, m = item[0], item[1]
        st = item[2] if len(item) > 2 else pp_state
        out = eng.assess(st, m)
        a = out["attribution"]
        print("\n[%s] -> mode=%s | attribution=%s | cgm_driver=%s | tier=%s"
              % (label, out["output_mode"], a["label"], a["cgm_driver"], out["phenotype"]["tier"]))
        print("   fact:", out["fact"])
        if out["lever"]: print("   lever:", out["lever"]["say"], "(%+g, %s)" % (out["lever"]["effect_mgdl"], out["lever"]["cite"]))
        if a["physiology_signal"]: print("   physiology:", a["physiology_signal"])
    print("\nEngine v2 demo OK — structured contract only, no patient prose authored.")
