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
import os, json, math
from datetime import date, datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
def _load(name, default):
    p = os.path.join(_HERE, "data", name)
    try:
        with open(p, "r", encoding="utf-8") as f: return json.load(f)
    except Exception:
        return default

LEVERS_DATA = _load("levers.json", {"levers": {}, "circadian_breakfast_mgdl": 12.35})
PHENO = _load("phenotype_lookup.json", {})
SPIKE = _load("spike_model.json", None)   # validated GBM regressor (AUROC 0.787 sibling), exported as plain trees
BMIQ_EVIDENCE = _load("bmiq_evidence_library.json", {"dimensionTargets": [], "riskRules": []})


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

def slot(h): return 0 if 5 <= h < 11 else 1 if 11 <= h < 16 else 2 if 16 <= h < 22 else 3

def _num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except Exception: return None

_GLP1 = ("glp", "semaglutide", "liraglutide", "dulaglutide", "tirzepatide", "exenatide",
         "ozempic", "rybelsus", "mounjaro", "wegovy", "trulicity", "victoza", "saxenda")
def _glp1(prof):
    meds = prof.get("meds") or prof.get("medications") or []
    s = " ".join(str(m).lower() for m in meds) if isinstance(meds, (list, tuple)) else str(meds).lower()
    return any(k in s for k in _GLP1)

DRAFT_FAST_LOSS_PCT_PER_WEEK = 1.5  # DRAFT: clinician sign-off needed before patient-facing use
DRAFT_WAIST_SCORE_RAMP = "DRAFT_WAIST_SCORE_RAMP_IDF_SOUTH_ASIAN_ACTION_LEVELS"

def _interp(x, xp, fp):
    if x is None:
        return None
    if x <= xp[0]:
        return float(fp[0])
    if x >= xp[-1]:
        return float(fp[-1])
    for i in range(1, len(xp)):
        if x <= xp[i]:
            x0, x1 = xp[i - 1], xp[i]
            y0, y1 = fp[i - 1], fp[i]
            if x1 == x0:
                return float(y1)
            return float(y0 + (y1 - y0) * ((x - x0) / (x1 - x0)))
    return float(fp[-1])

def _avg(vals):
    vals = [v for v in vals if v is not None]
    return (sum(vals) / len(vals)) if vals else None

def _clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))

def _sex(x):
    s = str(x or "").strip().lower()
    if s.startswith("m"):
        return "M"
    if s.startswith("f") or s.startswith("w"):
        return "F"
    return None

def _parse_date(x):
    if isinstance(x, datetime):
        return x.replace(tzinfo=None) if x.tzinfo is not None else x
    if isinstance(x, date):
        return datetime.combine(x, datetime.min.time())
    if x is None:
        return None
    s = str(x).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(s)
        return d.replace(tzinfo=None) if d.tzinfo is not None else d
    except Exception:
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(s[:10], fmt)
            except Exception:
                pass
    return None

def _as_records(x):
    if isinstance(x, list):
        return [r for r in x if isinstance(r, dict)]
    if isinstance(x, tuple):
        return [r for r in x if isinstance(r, dict)]
    return []

def _record_date(r):
    for k in ("date", "test_date", "scan_date", "measured_at", "created_at", "captured_at", "week_end"):
        d = _parse_date(r.get(k))
        if d is not None:
            return d
    return None

def _sort_records(records):
    indexed = list(enumerate(records))
    indexed.sort(key=lambda item: (_record_date(item[1]) or datetime.min, item[0]))
    return [r for _, r in indexed]

def _first_num(sources, names):
    for src in sources:
        if not isinstance(src, dict):
            continue
        for name in names:
            if name in src:
                v = _num(src.get(name))
                if v is not None:
                    return v, name
    return None, None

def _first_value(sources, names):
    for src in sources:
        if not isinstance(src, dict):
            continue
        for name in names:
            if src.get(name) not in (None, ""):
                return src.get(name), name
    return None, None


class MetabolicEngine:
    def __init__(self, levers=None, phenotype=None, prior_slope=PRIOR_SLOPE, bmiq_evidence=None):
        self.L = (levers or LEVERS_DATA).get("levers", {})
        self.circadian = (levers or LEVERS_DATA).get("circadian_breakfast_mgdl", CIRCADIAN_BF)
        self.restraint_cite = (levers or LEVERS_DATA).get("restraint_cite", "")
        self.dawn_guardrail = (levers or LEVERS_DATA).get("dawn_guardrail", "")
        self.PH = phenotype or PHENO
        self.prior_slope = prior_slope
        self.spike = SpikeModel(SPIKE)
        self.B = bmiq_evidence or BMIQ_EVIDENCE
        self.bmiq_weights = {d["dimId"]: float(d["weight"]) for d in self.B.get("dimensionTargets", []) if d.get("dimId")}
        if not self.bmiq_weights:
            self.bmiq_weights = {"D1_adiposity": 0.30, "D2_visceral": 0.30, "D3_sarcopenia": 0.25, "D4_fluid": 0.15}
        self.bmiq_rules = {r["ruleId"]: r for r in self.B.get("riskRules", []) if r.get("ruleId")}

    # ---- personal carb slope, shrunk to the population prior on thin history ----
    def personal_slope(self, history):
        xs = [h["carb"] for h in history if h.get("carb") and h.get("peak") is not None]
        ys = [h["peak"] for h in history if h.get("carb") and h.get("peak") is not None]
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

    def _bmiq_sources(self, patient_state):
        prof = patient_state.get("profile") or {}
        direct_inbody = (patient_state.get("inbody") or patient_state.get("inbody_summary") or
                         patient_state.get("latest_inbody") or prof.get("inbody") or {})
        direct_inbody = direct_inbody if isinstance(direct_inbody, dict) else {}
        inbody_series = (_as_records(patient_state.get("inbody_series")) or
                         _as_records(patient_state.get("inbody_history")) or
                         _as_records(direct_inbody.get("series")) or
                         _as_records(prof.get("inbody_series")))
        latest_series = _sort_records(inbody_series)[-1] if inbody_series else {}
        sources = [latest_series, direct_inbody, prof, patient_state]
        return prof, direct_inbody, inbody_series, sources

    def _bmiq_inputs(self, patient_state):
        prof, direct_inbody, inbody_series, sources = self._bmiq_sources(patient_state)
        out = {}
        present = []
        aliases = {
            "bmi": ("bmi", "BMI"),
            "waist_cm": ("waist_cm", "waist", "waist_circumference_cm", "waist_circumference"),
            "hip_cm": ("hip_cm", "hip", "hip_circumference_cm", "hip_circumference"),
            "whr": ("waist_hip_ratio", "whr", "WHR"),
            "body_fat_pct": ("body_fat_pct", "pbf_pct", "pbf", "percent_body_fat", "bodyfat_pct"),
            "visceral_fat_level": ("visceral_fat_level", "visceral_fat", "vfl"),
            "smm_kg": ("smm_kg", "skeletal_muscle_mass", "skeletal_muscle_mass_kg", "smm"),
            "height_cm": ("height_cm", "height"),
            "age": ("age",),
            "weight_kg": ("weight_kg", "weight"),
            "ecw_tbw": ("ecw_tbw", "ecw_tbw_ratio", "ecw_twb"),
            "fat_mass_kg": ("fat_mass_kg", "body_fat_mass", "body_fat_mass_kg", "fat_mass"),
            "obesity_degree_pct": ("obesity_degree_pct", "obesity_degree"),
        }
        for key, names in aliases.items():
            out[key], name = _first_num(sources, names)
            if out[key] is not None:
                present.append(key if name == key else "%s:%s" % (key, name))

        sex_raw, sex_name = _first_value(sources, ("sex", "gender"))
        out["sex"] = _sex(sex_raw)
        if out["sex"]:
            present.append("sex" if sex_name == "sex" else "sex:%s" % sex_name)

        if out.get("whr") is None and out.get("waist_cm") and out.get("hip_cm"):
            out["whr"] = out["waist_cm"] / out["hip_cm"] if out["hip_cm"] else None
            if out["whr"] is not None:
                present.append("whr:waist_hip")

        out["inbody_present"] = bool(direct_inbody or inbody_series)
        out["inputs_present"] = sorted(set(present))
        return out

    def _d1_adiposity(self, bmi, pbf, sex):
        parts = []
        if bmi is not None:
            parts.append(_interp(bmi, [18.5, 23, 25, 30, 35, 45], [10, 30, 50, 70, 90, 100]))
        if pbf is not None and sex in ("M", "F"):
            cut = [15, 20, 25, 30, 40] if sex == "M" else [22, 28, 32, 38, 48]
            parts.append(_interp(pbf, cut, [10, 30, 55, 80, 100]))
        return _avg(parts)

    def _waist_score(self, waist_cm, sex):
        if waist_cm is None:
            return None
        if sex == "M":
            return _interp(waist_cm, [80, 90, 100, 110, 125], [10, 40, 65, 85, 100])
        if sex == "F":
            return _interp(waist_cm, [70, 80, 90, 100, 115], [10, 40, 65, 85, 100])
        return _interp(waist_cm, [75, 85, 95, 105, 120], [10, 40, 65, 85, 100])

    def _d2_visceral(self, vfl, whr, waist_cm, sex):
        parts = []
        if vfl is not None:
            parts.append(_interp(vfl, [5, 10, 15, 20, 30], [10, 40, 65, 85, 100]))
        if whr is not None and sex in ("M", "F"):
            cut = [0.85, 0.90, 0.95, 1.0, 1.1] if sex == "M" else [0.78, 0.85, 0.90, 0.95, 1.05]
            parts.append(_interp(whr, cut, [10, 40, 60, 80, 100]))
        if waist_cm is not None:
            parts.append(self._waist_score(waist_cm, sex))
        return _avg(parts)

    def _d3_sarcopenia(self, smm, height_cm, pbf, sex):
        if smm is None or height_cm is None or height_cm <= 0 or sex not in ("M", "F"):
            return None, False, None
        smi = smm / ((height_cm / 100.0) ** 2)
        lo, hi = (9.5, 11.5) if sex == "M" else (8.0, 10.0)
        cut = 10.0 if sex == "M" else 8.5
        deficit = _clamp(100.0 * (hi - smi) / (hi - lo))
        fat_high = pbf is not None and ((sex == "M" and pbf >= 25) or (sex == "F" and pbf >= 32))
        return deficit, bool(smi < cut and fat_high), smi

    def _d4_fluid(self, ecw_tbw):
        if ecw_tbw is None:
            return None, False
        return _clamp(_interp(ecw_tbw, [0.34, 0.36, 0.39, 0.40, 0.42], [5, 15, 55, 85, 100])), ecw_tbw > 0.39

    @staticmethod
    def _bmiq_tier(score):
        if score is None:
            return "Unscored"
        if score < 35:
            return "Low"
        if score < 55:
            return "Moderate"
        if score < 75:
            return "High"
        return "Very High"

    def _rule_anchor(self, rule_id):
        r = self.bmiq_rules.get(rule_id) or {}
        return {
            "rule_id": rule_id,
            "effect_size": r.get("effectSize"),
            "citation": r.get("citation"),
            "recommended_action": r.get("recommendedAction"),
        }

    def _bmiq_score(self, patient_state):
        inp = self._bmiq_inputs(patient_state)
        sex = inp.get("sex")
        d1 = self._d1_adiposity(inp.get("bmi"), inp.get("body_fat_pct"), sex)
        d2 = self._d2_visceral(inp.get("visceral_fat_level"), inp.get("whr"), inp.get("waist_cm"), sex)
        d3, sarco, smi = self._d3_sarcopenia(inp.get("smm_kg"), inp.get("height_cm"), inp.get("body_fat_pct"), sex)
        d4, fluid = self._d4_fluid(inp.get("ecw_tbw"))
        dims = {"D1_adiposity": d1, "D2_visceral": d2, "D3_sarcopenia": d3, "D4_fluid": d4}
        num = sum(self.bmiq_weights.get(k, 0.0) * v for k, v in dims.items() if v is not None)
        den = sum(self.bmiq_weights.get(k, 0.0) for k, v in dims.items() if v is not None)
        score = round(num / den, 1) if den > 0 else None
        present_dims = {k: round(v, 1) for k, v in dims.items() if v is not None}
        driver = max(present_dims, key=present_dims.get) if present_dims else "unknown"

        flags = []
        anchors = []
        if sarco:
            flags.append("sarcopenic_obesity")
            anchors.append(self._rule_anchor("SARCOPENIC_OBESITY"))
        if inp.get("visceral_fat_level") is not None and inp["visceral_fat_level"] >= 15:
            flags.append("high_visceral")
            anchors.append(self._rule_anchor("HIGH_VISCERAL"))
        waist = inp.get("waist_cm")
        if waist is not None and ((sex == "M" and waist >= 90) or (sex == "F" and waist >= 80)):
            flags.append("central_obesity")
        if fluid:
            flags.append("fluid_overload")
            anchors.append(self._rule_anchor("FLUID_OVERLOAD"))
        if not inp.get("inbody_present"):
            flags.append("inbody_absent_bmi_waist_only")

        confidence = "high" if len(present_dims) >= 3 else "moderate" if len(present_dims) >= 2 else "low" if present_dims else "unscored"
        return {
            "score": score,
            "tier": self._bmiq_tier(score),
            "driver": driver,
            "flags": flags,
            "inputs_present": inp["inputs_present"],
            "dimensions": present_dims,
            "confidence": confidence,
            "smi": round(smi, 1) if smi is not None else None,
            "risk_anchors": [a for a in anchors if a.get("citation") or a.get("effect_size")],
            "draft_thresholds": [DRAFT_WAIST_SCORE_RAMP] if inp.get("waist_cm") is not None else [],
            "_inputs": inp,
        }

    def _series_candidates(self, patient_state, kind):
        prof = patient_state.get("profile") or {}
        inbody = patient_state.get("inbody") or patient_state.get("inbody_summary") or patient_state.get("latest_inbody") or {}
        inbody = inbody if isinstance(inbody, dict) else {}
        keys = ("weight_series", "weight_history", "weights") if kind == "weight" else ("inbody_series", "inbody_history")
        records = []
        for src in (patient_state, prof, inbody):
            if not isinstance(src, dict):
                continue
            for key in keys:
                records += _as_records(src.get(key))
        if kind == "weight" and not records:
            records += _as_records(patient_state.get("inbody_series")) + _as_records(patient_state.get("inbody_history"))
        return _sort_records(records)

    def _weight_trend(self, patient_state, glp1_flag):
        weight_records = self._series_candidates(patient_state, "weight")
        weight_points = []
        for r in weight_records:
            w, _ = _first_num([r], ("weight_kg", "weight"))
            d = _record_date(r)
            if w is not None:
                weight_points.append((d, w, r))

        out = {
            "available": False,
            "points": len(weight_points),
            "start_weight_kg": None,
            "end_weight_kg": None,
            "days": None,
            "weight_change_kg": None,
            "weight_change_pct": None,
            "loss_velocity_pct_per_week": None,
            "quality": None,
            "flags": [],
            "body_comp": {},
            "draft_thresholds": [],
        }
        if len(weight_points) < 2:
            return out

        start_d, start_w, _ = weight_points[0]
        end_d, end_w, _ = weight_points[-1]
        out.update({
            "available": True,
            "start_weight_kg": round(start_w, 1),
            "end_weight_kg": round(end_w, 1),
            "weight_change_kg": round(end_w - start_w, 1),
            "weight_change_pct": round(((end_w - start_w) / start_w) * 100.0, 1) if start_w else None,
        })
        if start_d is not None and end_d is not None and end_d > start_d:
            days = max(1, (end_d - start_d).days)
            weeks = days / 7.0
            out["days"] = days
            if out["weight_change_pct"] is not None:
                out["loss_velocity_pct_per_week"] = round(max(0.0, -out["weight_change_pct"]) / weeks, 2)
                if out["loss_velocity_pct_per_week"] > DRAFT_FAST_LOSS_PCT_PER_WEEK:
                    out["flags"].append("fast_weight_loss_velocity")
                    out["draft_thresholds"].append("DRAFT_FAST_LOSS_PCT_PER_WEEK_%s" % DRAFT_FAST_LOSS_PCT_PER_WEEK)

        inbody_records = self._series_candidates(patient_state, "inbody")
        if len(inbody_records) >= 2:
            first, last = inbody_records[0], inbody_records[-1]
            smm0, _ = _first_num([first], ("smm_kg", "skeletal_muscle_mass", "skeletal_muscle_mass_kg", "smm"))
            smm1, _ = _first_num([last], ("smm_kg", "skeletal_muscle_mass", "skeletal_muscle_mass_kg", "smm"))
            fat0, _ = _first_num([first], ("fat_mass_kg", "body_fat_mass", "body_fat_mass_kg", "fat_mass"))
            fat1, _ = _first_num([last], ("fat_mass_kg", "body_fat_mass", "body_fat_mass_kg", "fat_mass"))
            vf0, _ = _first_num([first], ("visceral_fat_level", "visceral_fat", "vfl"))
            vf1, _ = _first_num([last], ("visceral_fat_level", "visceral_fat", "vfl"))
            body_comp = {}
            weight_loss_kg = max(0.0, start_w - end_w)
            if smm0 is not None and smm1 is not None:
                smm_delta = smm1 - smm0
                smm_pct = (smm_delta / smm0) * 100.0 if smm0 else None
                lean_fraction = max(0.0, -smm_delta) / weight_loss_kg if weight_loss_kg > 0 and smm_delta < 0 else None
                body_comp.update({
                    "smm_change_kg": round(smm_delta, 1),
                    "smm_change_pct": round(smm_pct, 1) if smm_pct is not None else None,
                    "lean_fraction_of_weight_lost": round(lean_fraction, 2) if lean_fraction is not None else None,
                })
                if smm_pct is not None and smm_pct <= -2.0:
                    out["flags"].append("rapid_lean_loss" if glp1_flag else "lean_loss_over_2pct")
                if lean_fraction is not None and lean_fraction > 0.30:
                    out["flags"].append("lean_loss_bad")
                    out["draft_thresholds"].append("DRAFT_LEAN_FRACTION_GT_30PCT_INTERNAL_C1")
            if fat0 is not None and fat1 is not None:
                body_comp["fat_mass_change_kg"] = round(fat1 - fat0, 1)
            if vf0 is not None and vf1 is not None:
                body_comp["visceral_fat_level_change"] = round(vf1 - vf0, 1)
            out["body_comp"] = body_comp

            lean_bad = "lean_loss_bad" in out["flags"] or "rapid_lean_loss" in out["flags"]
            fat_down = body_comp.get("fat_mass_change_kg") is not None and body_comp["fat_mass_change_kg"] < 0
            vf_not_worse = body_comp.get("visceral_fat_level_change") is None or body_comp["visceral_fat_level_change"] <= 0
            if weight_loss_kg >= 2.0 and fat_down and vf_not_worse and not lean_bad:
                out["quality"] = "fat_loss_good"
                out["flags"].append("fat_loss_good")
            elif lean_bad:
                out["quality"] = "lean_loss_bad"

        out["flags"] = sorted(set(out["flags"]))
        out["draft_thresholds"] = sorted(set(out["draft_thresholds"]))
        return out

    def _bmiq_lever(self, bmiq, trend, glp1_flag):
        flags = set(bmiq.get("flags", []))
        driver = bmiq.get("driver")
        if glp1_flag or driver == "D3_sarcopenia":
            return {
                "name": "resistance_activity",
                "target": "D3_sarcopenia",
                "priority": "protect_lean_mass",
                "cite": self._rule_anchor("GLP1_LEAN_LOSS").get("citation") or "BMIQ evidence GLP1_LEAN_LOSS",
                "evidence": "BMIQ:GLP1_LEAN_LOSS + nudge_vault:glp1_muscle_preserve",
                "supporting_levers": ["protein_adequacy", "gi_tolerance_hydration"] if glp1_flag else ["protein_adequacy"],
                "no_med_change": True,
            }
        if "high_visceral" in flags or "central_obesity" in flags or driver == "D2_visceral":
            return {
                "name": "waist_and_visceral_tracking",
                "target": "D2_visceral",
                "priority": "central_adiposity",
                "cite": self._rule_anchor("HIGH_VISCERAL").get("citation") or "nudge_vault:obesity_asian_waist_target",
                "evidence": "BMIQ:HIGH_VISCERAL + nudge_vault:obesity_asian_waist_target",
                "no_med_change": True,
            }
        if driver == "D1_adiposity":
            return {
                "name": "low_energy_density_foods",
                "target": "D1_adiposity",
                "priority": "adiposity_burden",
                "cite": "nudge_vault:heat_water_rich_foods / obesity guideline low-energy-density cluster",
                "evidence": "nudge_vault:heat_water_rich_foods",
                "no_med_change": True,
            }
        return None

    def _bmiq_gate(self, bmiq, trend, glp1_flag):
        flags = set(bmiq.get("flags", [])) | set(trend.get("flags", []))
        clinician = []
        if "sarcopenic_obesity" in flags:
            clinician.append("sarcopenic_obesity")
        for f in ("rapid_lean_loss", "lean_loss_bad", "fast_weight_loss_velocity"):
            if f in flags:
                clinician.append(f)
        if clinician:
            return "FLAG", None, sorted(set(clinician))
        if trend.get("quality") == "fat_loss_good":
            return "REINFORCE", None, []
        if bmiq.get("score") is None:
            return "STATE_FACTS", None, []
        if bmiq.get("confidence") in ("moderate", "high") and bmiq.get("tier") in ("Moderate", "High", "Very High"):
            lever = self._bmiq_lever(bmiq, trend, glp1_flag)
            if lever and lever.get("cite"):                 # Forge P2: cited lever required for a SUGGEST
                return "SUGGEST", lever, []
            return "STATE_FACTS", None, []
        return "STATE_FACTS", None, []

    def _assess_bmiq(self, patient_state):
        prof = patient_state.get("profile") or {}
        glp1_flag = _glp1(prof)
        bmiq = self._bmiq_score(patient_state)
        trend = self._weight_trend(patient_state, glp1_flag)
        for flag in trend.get("flags", []):
            if flag not in bmiq["flags"]:
                bmiq["flags"].append(flag)
        if glp1_flag:
            bmiq["flags"].append("glp1_flag")
        bmiq["flags"] = sorted(set(bmiq["flags"]))
        mode, lever, clinician_flags = self._bmiq_gate(bmiq, trend, glp1_flag)
        bmiq.update({
            "output_mode": mode,
            "lever": lever,
            "clinician_flags": clinician_flags,
            "glp1_flag": glp1_flag,
            "glp1": {
                "flag": glp1_flag,
                "expected_appetite_suppression": bool(glp1_flag),
                "priorities": ["protein_adequacy", "resistance_activity"] if glp1_flag else [],
                "monitor": ["gi_tolerance", "hydration", "lean_mass", "weight_velocity"] if glp1_flag else [],
                "expected_lean_loss_benchmark": "GLP-1 lean loss ~25% of total weight lost" if glp1_flag else None,
                "velocity_vs_expected": ("above_DRAFT_fast_loss_band" if "fast_weight_loss_velocity" in trend.get("flags", [])
                                         else "not_flagged" if trend.get("available") and glp1_flag else None),
                "cite": self._rule_anchor("GLP1_LEAN_LOSS").get("citation") if glp1_flag else None,
                "no_med_change": True,
            },
        })
        bmiq.pop("_inputs", None)
        return bmiq, trend

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
            return "%dg carb, pre %s. Predicted peak about +%d mg/dL (driver: %s). Predicted, not yet observed." % (
                carb, prestr, round(max(0.0, rise)), drv)
        if rise < 15:
            f = "%dg carb, pre %s — no meaningful rise (observed peak %+d). This meal sat flat." % (carb, prestr, round(rise))
            if pre is not None and pre >= 180:
                f += " Pre-meal %d is high on its own — a baseline issue, not this plate." % pre
            return f
        c = max(0.0, min(carb_comp, rise))                  # cap parts to the observed rise
        z = max(0.0, min(circ, rise - c))
        b = max(0.0, min(pre_term, rise - c - z))
        rem = max(0.0, rise - c - z - b)
        base = "%dg carb, pre %s, observed peak +%d. Carbs explain about +%d" % (carb, prestr, round(rise), round(c))
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
        bmiq_block, weight_trend = self._assess_bmiq(patient_state)

        # PREDICTION: validated GBM spike model (stdlib walker); personal-slope is the fallback
        feat = {"carb": carb, "protein": prot, "fat": _num(meal.get("fat")), "fiber": fib,
                "calories": (cal or None), "hour_of_day": hour, "pre_meal_glucose": pre,
                "pre_meal_slope_30min": _num(base.get("pre_slope_30min")),
                "user_baseline_mean": baseline_mean,
                "glp1_flag": 1.0 if _glp1(prof) else 0.0, "age": age, "bmi": bmi}
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
