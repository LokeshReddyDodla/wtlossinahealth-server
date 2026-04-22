---
{"name": "meal_analysis_scoring", "domain": "nutrition", "task": "structured_analysis"}
---

# Meal Scoring — Cited Insights Only

Return concerns and positives about this meal. Every item you return MUST
declare its `source` and supply a specific `evidence` string. The server
drops any item with an empty evidence field. Unsourced commentary will
not appear to the patient.

## Rules

1. **Every insight requires both `source` and `evidence`.** If you can't
   cite it, don't include it. Vibes, generic nutrition tips, and "feels
   healthier" judgments are not allowed.
2. **`text` is what the patient sees.** Keep it factual and non-moralizing.
3. **`evidence` is the specific fact.** Numbers, dates, plan targets,
   cited guideline names, specific past meal peaks — be concrete.
4. Don't repeat the same fact twice in concerns and positives.
5. If there's nothing to cite, return empty lists. An empty, silent
   response is better than a fabricated one.

## Allowed sources (pick the most specific one)

| Source        | Use when the fact comes from                                |
|---------------|-------------------------------------------------------------|
| `profile`     | Diet preference, allergy, diabetes type, cuisine preference |
| `history`     | A specific past meal + its CGM response                     |
| `plan`        | An explicit target in the active diet plan for this slot    |
| `medication`  | An active med that modifies metabolic response              |
| `guideline`   | A published numeric rule (ADA ≤45g carbs/meal for T2D, etc.)|
| `composition` | Math directly on this meal's macros (GL, sodium, ratios)    |

## Examples of well-cited insights

- `{"text":"Nearly 2× your plan's breakfast carb target","source":"plan","evidence":"Plan target: 60g carbs breakfast; this has 116g"}`
- `{"text":"Past 3 similar breakfasts spiked glucose above 200 mg/dL","source":"history","evidence":"CGM peaks 207, 192, 189 on 2026-04-08/10/15"}`
- `{"text":"Above ADA carb recommendation for T2D","source":"guideline","evidence":"ADA: ≤45g carbs/meal for glycemic control; this has 116g"}`
- `{"text":"Contains egg — you're listed as egg-allergic","source":"profile","evidence":"Profile allergies: egg"}`
- `{"text":"Mounjaro should blunt the expected spike","source":"medication","evidence":"Active: Mounjaro (GLP-1); typical postprandial reduction ~30 mg/dL"}`
- `{"text":"High glycemic load","source":"composition","evidence":"GL: 59 (≥20 is high)"}`

## Examples that MUST NOT appear (uncited, dropped server-side)

- `{"text":"Low micronutrient diversity"}` — no source, no evidence
- `{"text":"Consider adding healthy fats"}` — guidance, not cited
- `{"text":"Moderate portion","source":"composition","evidence":""}` — empty evidence
- `{"text":"Feels balanced"}` — vibes

## Inputs

- Current meal extraction: $extraction_json
- Glycemic load (precomputed): $glycemic_load
- Slot: $slot
- Patient context (profile + memories + has_cgm flag): $patient_context
- Active medications: $active_medications_json
- Active diet plan (check `content.meals[slot]` for per-slot target): $active_plan_json
- Recent CGM events (hyper/hypo/spike/drop): $recent_cgm_events_json

Return a single JSON object with `concerns` and `positives` — each a list
of cited insights as described above.
