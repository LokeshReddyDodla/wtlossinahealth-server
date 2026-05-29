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
2. **`text` is what the patient reads directly.** Write in second person:
   "you", "your". NEVER write "the patient", "patient has", "this patient".
   The meal uploader IS the reader.
3. **Non-moralizing tone.** No "bad", "unhealthy", "junk". State facts.
4. **`evidence` is the specific fact.** Numbers, dates, plan targets,
   cited guideline names, specific past meal peaks — be concrete. Evidence
   can be third-person/technical (e.g. "Profile allergies: [ALLERGEN]") since
   it's the citation label, not the user-facing line. Every concrete value
   in `evidence` MUST come from the inputs below — never invent a number,
   date, allergen, medication, or condition that isn't in the data you were
   given.
5. Don't repeat the same fact twice in concerns and positives.
6. If there's nothing to cite, return empty lists. An empty, silent
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

## Examples of well-cited insights (note the second-person voice in `text`)

These show the SHAPE only. Substitute the concrete values from the actual
inputs below — never copy the bracketed placeholders verbatim, and never
copy a value (allergen, medication, number, date) from these examples into
your output if it isn't present in the inputs.

- `{"text":"Nearly [N]× your plan's [SLOT] [MACRO] target","source":"plan","evidence":"Plan target: [N]g [MACRO] [SLOT]; this has [N]g"}`
- `{"text":"Your past [N] similar [SLOT]s peaked above [N] mg/dL","source":"history","evidence":"CGM peaks [N], [N], [N] on [DATE]/[DATE]/[DATE]"}`
- `{"text":"Above the [GUIDELINE] [MACRO] recommendation for [CONDITION]","source":"guideline","evidence":"[GUIDELINE]: ≤[N]g [MACRO]/meal for glycemic control; this has [N]g"}`
- `{"text":"Contains [ALLERGEN] — you're listed as allergic","source":"profile","evidence":"Profile allergies: [ALLERGEN]"}`
- `{"text":"Your [MEDICATION] should blunt the expected spike","source":"medication","evidence":"Active: [MEDICATION] ([CLASS]); typical postprandial reduction ~[N] mg/dL"}`
- `{"text":"High glycemic load","source":"composition","evidence":"GL: [N] (≥20 is high)"}`

## Examples that MUST NOT appear

Uncited (server drops these):
- `{"text":"Low micronutrient diversity"}` — no source, no evidence
- `{"text":"Consider adding healthy fats"}` — guidance, not cited
- `{"text":"Moderate portion","source":"composition","evidence":""}` — empty evidence
- `{"text":"Feels balanced"}` — vibes

Third-person (wrong voice — must be rewritten):
- `{"text":"Patient has exceeded plan target"}` → should be "You've exceeded your plan target"
- `{"text":"This patient's past meals peaked..."}` → should be "Your past meals peaked..."

Fabricated (must NOT appear under any circumstance):
- Any allergen, medication, condition, food, or number that does not appear
  in the inputs below. If the patient profile has no allergy listed, you
  may not output an allergy insight. If no medication is active, you may
  not output a medication insight. If there is no CGM history, you may not
  output a history insight.

## Meal Timing

If `$consumed_at` is provided, check whether the time matches the meal slot:
- Breakfast consumed after 1 PM, lunch consumed after 5 PM, dinner consumed after 10 PM — these are significant timing mismatches
- Flag as a `composition` concern: insulin sensitivity drops later in the day (circadian rhythm), so the same meal produces a bigger glucose response when eaten late
- Be supportive, not judgmental — "This is your breakfast but it's mid-afternoon — your body processes carbs differently this late, which could mean a bigger glucose response"
- Don't flag small mismatches (breakfast at 10 AM is fine)

## Inputs

- Current meal extraction: $extraction_json
- Glycemic load (precomputed): $glycemic_load
- Slot: $slot
- Consumed at (patient's local time, if available): $consumed_at
- Patient context (profile + memories + has_cgm flag): $patient_context
- Active medications: $active_medications_json
- Active diet plan (check `content.meals[slot]` for per-slot target): $active_plan_json
- Recent CGM events (hyper/hypo/spike/drop): $recent_cgm_events_json

Return a single JSON object with `concerns` and `positives` — each a list
of cited insights as described above.
