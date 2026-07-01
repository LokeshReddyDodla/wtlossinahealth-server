# Metabolic Engine — Clinical Validation State

Last updated: 2026-07-01

This document maps every clinical decision in the metabolic engine to its evidence basis, validation status, and what needs clinician sign-off before patient-facing use.

**Confidence tiers used below:**
- **VALIDATED** — externally published evidence or our own validated cohort (n cited)
- **INTERNAL** — derived from our data, reproduced, not yet externally validated
- **DRAFT** — placeholder heuristic, needs derivation or clinician sign-off

---

## 1. Glucose Prediction

### Spike Model (GBM Regressor)
| Item | Status | Evidence |
|------|--------|----------|
| Model type | VALIDATED | GradientBoosting exported as pure-stdlib tree-walker (`spike_model.json`) |
| Performance | VALIDATED | AUROC 0.787 (sibling model), trained on validated cohort |
| Fallback | VALIDATED | Personal carb slope with Bayesian shrinkage to population prior (slope=0.40 mg/dL per g carb), kicks in when GBM unavailable |
| Cold-start shrinkage | INTERNAL | k=10 shrinkage strength, n<5 meals = population prior only |
| Fail-closed | VALIDATED | `SpikeModel.ok=False` on any malformed export; cycle guard in tree walk prevents hangs |

### Meal Levers (Coaching Suggestions)
All levers sourced from `levers.json`, derived from the MMIQ v3.1 validated cohort (2,674 patients, 38,325 meals, 5.12M CGM readings).

| Lever | Effect | Citation | Status |
|-------|--------|----------|--------|
| Protein first (veg/dal first, carbs last) | -7.5 mg/dL | q1 meal sequencing (n=28,082, p=1e-4) | VALIDATED |
| Fibre source | -6.0 mg/dL | q3 fibre (n=38,305, p=1e-4) | VALIDATED |
| Protein pairing | -8.2 mg/dL | q4 pairing (n=45,906, p=1e-4) | VALIDATED |
| Earlier dinner (<8:30pm) | -9.1 mg/dL | q7 late dinner (n=2,539, p=4e-4) | VALIDATED |
| Circadian breakfast add | +12.35 mg/dL | q2 time-of-day (n=38,325, p=5e-4) | VALIDATED |

### Output Mode Gate (Zero Hallucination)
| Rule | Status | Notes |
|------|--------|-------|
| SUGGEST requires cited lever | VALIDATED | Forge P2: if no citation, downgrade to STATE_FACTS |
| SUGGEST requires n>=8 meals + MEAL_DRIVEN attribution | INTERNAL | Threshold from learning curve plateau |
| REINFORCE on in-range + balanced plate | VALIDATED | No coaching needed when meal is fine |
| FLAG_PHYSIOLOGY when attribution is physiology-driven | VALIDATED | Never blames a balanced plate for a physiology spike |
| SAFETY overrides everything (pre<80 or pre>250) | VALIDATED | Forge P0: inviolable, including cross-axis BMIQ lock |

---

## 2. Attribution

### Meal vs Physiology Decomposition
| Component | Status | Evidence |
|-----------|--------|----------|
| Carb component (personal slope * carb g) | VALIDATED | Per-patient OLS with shrinkage |
| Circadian component (breakfast +12.35) | VALIDATED | q2 cohort finding |
| Pre-meal baseline term (0.12 * (pre-100)) | INTERNAL | Heuristic, captures elevated-baseline contribution |
| Residual (observed - carb - circadian) | VALIDATED | Whatever the model can't explain = physiology |

### CGM Driver Decomposition (MMIQ B1)
| Driver | Status | Evidence |
|--------|--------|----------|
| Postprandial / nocturnal / basal / mixed | VALIDATED | From CGM out-of-range share by time window |
| Driver-consistent cross-check | INTERNAL | Resolves MIXED attribution using patient-level CGM driver |
| Recent-state unstable override (CV>36 or mean>=160) | INTERNAL | mean24/cv24 dominate spike variance; macros alone ~0 |

### Slot Carb Targets
| Slot | Target (g) | Status |
|------|-----------|--------|
| Breakfast | 50 | **DRAFT** — must be pinned to ADA / diabetes-India MNT |
| Lunch | 55 | **DRAFT** — must be pinned to ADA / diabetes-India MNT |
| Dinner | 45 | **DRAFT** — must be pinned to ADA / diabetes-India MNT |
| Snack | 20 | **DRAFT** — must be pinned to ADA / diabetes-India MNT |

### Balanced Plate Rule
| Check | Threshold | Status |
|-------|-----------|--------|
| Carb <= target * 1.15 | Slot-dependent | **DRAFT** — tied to slot targets above |
| Fibre >= 4g | Per meal | **DRAFT** — needs MNT pinning |
| Protein >= 10g | Per meal | **DRAFT** — needs MNT pinning |
| Calories <= 750 | Per meal | **DRAFT** — needs MNT pinning |

---

## 3. Safety Gates

| Gate | Threshold | Status | Notes |
|------|-----------|--------|-------|
| PRE_HYPO | pre < 80 mg/dL | VALIDATED | Overrides all coaching, routes to care team |
| PRE_VERY_HIGH | pre > 250 mg/dL | VALIDATED | Overrides all coaching, routes to care team |
| LARGE_EXCURSION_REVIEW | rise > 120 mg/dL | INTERNAL | Flag only, does not override |
| NO_MED_CHANGE | Always present | VALIDATED | Engine never suggests medication changes |
| Cross-axis BMIQ safety hold | On SAFETY mode | VALIDATED | Forge P0: BMIQ axis forced to SAFETY_HOLD when glucose is hypo/very-high |

### v3.1 Safety Enrichment
| Feature | Status | Evidence |
|---------|--------|----------|
| `safety_unchecked` flag (no live pre-meal glucose) | VALIDATED | Doctor's gap response: safety gate cannot run without live reading |
| 15-minute CGM freshness window | VALIDATED | Doctor specified: readings older than 15 min are stale |
| Twin prior (90-day AGP fallback) for prediction only | VALIDATED | Never feeds safety gate, tagged as prior |
| `show_number_to_patient` (suppress for non-CGM) | VALIDATED | Doctor's gap response: no personal number without CGM signal |

---

## 4. BMIQ (Body Composition Risk Index)

### Dimension Scoring
Validated on 706-patient cohort. C1 longitudinal: 127 patients, median 196 days.

| Dimension | Weight | Inputs | Status |
|-----------|--------|--------|--------|
| D1 Adiposity | 0.30 | BMI (Asian cutoffs), sex-specific body-fat% | VALIDATED |
| D2 Visceral | 0.30 | InBody visceral level, waist-hip ratio | VALIDATED |
| D3 Sarcopenia | 0.25 | SMM-index deficit (sex-specific) | VALIDATED |
| D4 Fluid | 0.15 | ECW/TBW ratio | VALIDATED |

Note: D3 weight raised 0.20→0.25 in v2 because SMI is the single strongest discriminator of high-risk phenotype (r=-0.50).

### Risk Rules
| Rule | Condition | Effect Size | Citation | Status |
|------|-----------|-------------|----------|--------|
| Sarcopenic Obesity | SMI < cut AND body fat high | Published meta | BMIQ evidence library | VALIDATED |
| High Visceral | VFL >= 15 | CKD OR 3.94 (2.44-6.39) | Yu P et al. Front Endocrinol 2022 | VALIDATED |
| Fluid Overload | ECW/TBW > 0.39 | +24.5% mortality per +0.1 E:I | Ng JK et al. PLoS One 2018 | VALIDATED |
| GLP-1 Lean Loss | On GLP-1 AND >2% SMM loss | ~25% of weight lost as lean (RCT meta) | Karakasis P et al. Metabolism 2024 | VALIDATED |
| Muscle-Loss-Predominant | SMM down >2%, fat flat/up, weight stable | Internal finding (n=7/127) | BMIQ eating report 2026-06-17 | INTERNAL |

### Weight Trend Thresholds
| Threshold | Value | Status | Notes |
|-----------|-------|--------|-------|
| Fast weight loss velocity | >1.5% per week | **DRAFT** | Needs clinician sign-off before patient-facing |
| Lean fraction of weight lost | >30% | **DRAFT** | Internal C1 finding, pending external anchor |
| Waist score ramp | IDF South Asian action levels | **DRAFT** | Needs IDF threshold pinning |

---

## 5. Data Sufficiency

### Source Requirements
| Source | Min Unlock | Ideal | Confidence | Basis |
|--------|-----------|-------|------------|-------|
| CGM | 14 days @ >=70% wear | 14 | **HIGH** | Battelino 2019, Diabetes Care; ADA SoC |
| Food photos (paired meals) | 8 | 30 | **MODERATE** | Our learning curve (n=15 patients), plateau 8/30/60 |
| Labs (A1c/insulin) | 1 | 3 | **HIGH** | ADA: A1c q3 months; >=3 for reliable trend |
| Medications | 1 | 1 | **HIGH** | Definitional |
| Body comp (InBody) | 1 | 2 | **MODERATE** | 706-cohort (BMIQ); serial from C1 (127 patients) |
| Fitness (wearable) | 14 days | 14 | **DRAFT** | Placeholder — steps were NULL as a predictor |
| Sleep (wearable) | 14 nights | 14 | **DRAFT** | Placeholder — sleep-CGM link is N=1 to N=2, unproven |
| Fundus (retinal) | 1 image | 2 | **HIGH** | Standard retinopathy screening |
| Vitals (BP/HR) | 3 readings | 3 | **DRAFT** | Arbitrary, not derived |
| Mood logs | 7 | 14 | **DRAFT** | Arbitrary, needs paired mood-glucose events |
| Symptoms | 7 | 14 | **DRAFT** | Arbitrary, needs paired symptom-glucose events |

**Gating rule:** Only HIGH and MODERATE confidence sources gate or weaken a number. DRAFT sources are feedback/nudge only and must NEVER gate a prediction.

### Learning Curve (Personal Model)
Source: RESEARCH_MASTER/LEARNING_CURVE.md (n=15 patients, >=80 meals each)

| Own Meals | Expected MAE (mg/dL) | Within +/-35 Band | Tier |
|-----------|---------------------|-------------------|------|
| 0 | 28.5 | 62% | cold_start |
| 5 | 24.5 | 75% | cold_start |
| 8 | — | — | emerging (SUGGEST gate opens) |
| 20 | 24.7 | 79% | emerging → personal |
| 30 | 23.9 | 76% | personal |
| 60 | 19.6 | 83% | rich |

---

## 6. v3.1 Enrichment (Additive, Never Touches Core)

| Feature | Status | Evidence |
|---------|--------|----------|
| Peak minutes (personal per-slot median, >=3 meals) | INTERNAL | Median of time-to-peak from same-slot history |
| Peak minutes (composition heuristic fallback) | **DRAFT** | Base by slot + fat/fiber/carb modifiers |
| Evidence meals (top-3 similar by carb proximity) | INTERNAL | Similarity search, not clinically validated |
| Confidence tier (high/moderate/cold_start/low_no_cgm/moderate_prior) | INTERNAL | Maps data availability to confidence label |
| Twin pre-meal prior (90-day AGP at this hour) | VALIDATED | Doctor approved; tagged as prior, never safety input |

---

## 7. Outcome Loop

| Feature | Status | Notes |
|---------|--------|-------|
| Advice event logging | INTERNAL | Append-only JSONL; only cited SUGGEST events logged (Forge P1) |
| Compliance follow-up | INTERNAL | Mechanism validated (synthetic); needs live CGM/InBody wiring |
| Rollup (per-trigger efficacy) | INTERNAL | Valid flag requires >=10 followed-up events |
| Live wiring | **NOT DONE** | Needs read-only service token for CGM + InBody follow-up |

---

## Summary: What Needs Sign-Off Before Patient-Facing

1. **Slot carb targets** (50/55/45/20g) — pin to ADA / diabetes-India MNT guidelines
2. **Balanced plate thresholds** (fibre 4g, protein 10g, cal 750) — pin to MNT
3. **Fast weight loss velocity** (1.5%/week) — clinician sign-off
4. **Lean fraction threshold** (30%) — pending external anchor
5. **Waist score ramp** — pin to IDF South Asian action levels
6. **Peak minutes heuristic** (slot base + fat/carb modifiers) — needs validation against CGM time-to-peak data
7. **Fitness/sleep/vitals/mood/symptoms source thresholds** — all DRAFT, arbitrary values
