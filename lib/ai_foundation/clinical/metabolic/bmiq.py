"""
BMIQ scoring — body-composition risk index, weight trending, and obesity-axis coaching.

Separated from the glucose engine because these are distinct clinical axes:
glucose prediction uses CGM + meal macros; BMIQ uses InBody/anthropometry + weight series.
Both feed the same contract but evolve independently.

Pure stdlib, stateless per patient. Evidence-backed: dimension targets and risk rules
from bmiq_evidence_library.json (validated on 706-patient cohort, C1 longitudinal 127 patients).
"""
import os, json
from datetime import date, datetime

from .util import num as _num

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, default):
    p = os.path.join(_HERE, "data", name)
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


BMIQ_EVIDENCE = _load("bmiq_evidence_library.json", {"dimensionTargets": [], "riskRules": []})

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


class BmiqScorer:
    """Body-composition risk scoring, weight trending, and obesity-axis coaching gate.

    Owns: BMIQ dimensions (adiposity, visceral, sarcopenia, fluid), weight trend analysis,
    lever selection, and output-mode gating. Does NOT own the cross-axis safety lock
    (that stays in MetabolicEngine.assess since it's a glucose×BMIQ concern).
    """

    def __init__(self, evidence=None):
        ev = evidence or BMIQ_EVIDENCE
        self._weights = {d["dimId"]: float(d["weight"]) for d in ev.get("dimensionTargets", []) if d.get("dimId")}
        if not self._weights:
            self._weights = {"D1_adiposity": 0.30, "D2_visceral": 0.30, "D3_sarcopenia": 0.25, "D4_fluid": 0.15}
        self._rules = {r["ruleId"]: r for r in ev.get("riskRules", []) if r.get("ruleId")}

    def assess(self, patient_state, glp1_flag=False):
        """Full BMIQ + weight trend. Returns (bmiq_block, weight_trend)."""
        bmiq = self._score(patient_state)
        trend = self._weight_trend(patient_state, glp1_flag)
        for flag in trend.get("flags", []):
            if flag not in bmiq["flags"]:
                bmiq["flags"].append(flag)
        if glp1_flag:
            bmiq["flags"].append("glp1_flag")
        bmiq["flags"] = sorted(set(bmiq["flags"]))
        mode, lever, clinician_flags = self._gate(bmiq, trend, glp1_flag)
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

    # ---- data extraction ----

    def _sources(self, patient_state):
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

    def _inputs(self, patient_state):
        prof, direct_inbody, inbody_series, sources = self._sources(patient_state)
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

    # ---- dimension scorers ----

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
    def _tier(score):
        if score is None:
            return "Unscored"
        if score < 35:
            return "Low"
        if score < 55:
            return "Moderate"
        if score < 75:
            return "High"
        return "Very High"

    # ---- composite score ----

    def _rule_anchor(self, rule_id):
        r = self._rules.get(rule_id) or {}
        return {
            "rule_id": rule_id,
            "effect_size": r.get("effectSize"),
            "citation": r.get("citation"),
            "recommended_action": r.get("recommendedAction"),
        }

    def _score(self, patient_state):
        inp = self._inputs(patient_state)
        sex = inp.get("sex")
        d1 = self._d1_adiposity(inp.get("bmi"), inp.get("body_fat_pct"), sex)
        d2 = self._d2_visceral(inp.get("visceral_fat_level"), inp.get("whr"), inp.get("waist_cm"), sex)
        d3, sarco, smi = self._d3_sarcopenia(inp.get("smm_kg"), inp.get("height_cm"), inp.get("body_fat_pct"), sex)
        d4, fluid = self._d4_fluid(inp.get("ecw_tbw"))
        dims = {"D1_adiposity": d1, "D2_visceral": d2, "D3_sarcopenia": d3, "D4_fluid": d4}
        num = sum(self._weights.get(k, 0.0) * v for k, v in dims.items() if v is not None)
        den = sum(self._weights.get(k, 0.0) for k, v in dims.items() if v is not None)
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
            "tier": self._tier(score),
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

    # ---- weight trend ----

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

    # ---- lever + gate ----

    def _lever(self, bmiq, trend, glp1_flag):
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

    def _gate(self, bmiq, trend, glp1_flag):
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
            lever = self._lever(bmiq, trend, glp1_flag)
            if lever and lever.get("cite"):
                return "SUGGEST", lever, []
            return "STATE_FACTS", None, []
        return "STATE_FACTS", None, []
