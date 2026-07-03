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
7. **Prioritize by THIS patient's goals and conditions** (read the patient
   context below — never assume diabetes):
   - Glycemic condition (diabetes/prediabetes) or CGM user → glycemic load,
     carbs, and spike history lead.
   - Weight-loss goal → calorie density, protein adequacy, and satiety lead;
     GL is secondary (energy crashes and hunger rebound, not clinical risk).
   - Fitness/muscle goal → protein amount and timing lead.
   - No stated condition or goal → balanced general nutrition framing.
   The `text` WORDING must match the patient's frame too: a weight-loss
   patient reads "a lot of added sugar and calories for one snack", not
   "high glycemic load" — clinical glycemic language is for patients with a
   glycemic condition or CGM.

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
- `{"text":"Above the [GUIDELINE] [MACRO] recommendation for [CONDITION]","source":"guideline","evidence":"[GUIDELINE]: ≤[N]g [MACRO]/meal for glycemic control; this has [N]g"}` (glucose-focused patient)
- `{"text":"About [N]% of a typical day's calories in one [SLOT] — worth knowing with your weight goal","source":"guideline","evidence":"General guidance: ~[N] kcal/day for [GOAL]; this meal has [N] kcal"}` (weight-loss patient)
- `{"text":"Contains [ALLERGEN] — you're listed as allergic","source":"profile","evidence":"Profile allergies: [ALLERGEN]"}`
- `{"text":"Your [MEDICATION] supports your overall glucose control alongside meals like this","source":"medication","evidence":"Active: [MEDICATION] ([CLASS])"}`
  — Be pharmacologically accurate: only claim acute post-meal spike reduction
  for drug classes that actually do that (rapid-acting insulin, GLP-1 RAs).
  Metformin reduces hepatic glucose output over time; it does NOT meaningfully
  blunt an individual meal's spike — never claim that it will.
- `{"text":"High glycemic load","source":"composition","evidence":"GL: [N] (≥20 is high)"}` (glucose-focused patient)
- `{"text":"About [N] kcal and [N]g added sugar in one [SLOT] — a big share of a day's budget for your goal","source":"composition","evidence":"This meal: [N] kcal, [N]g sugar"}` (weight-loss patient)

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

If `$consumed_at` is provided, flag a timing concern ONLY when the time is
past these hard thresholds:
- Breakfast after 1 PM, lunch after 5 PM, dinner after 10 PM

Anything earlier gets NO timing insight at all — breakfast at 10 AM, lunch
at 1:30 PM, and dinner at 7:30 PM are all normal; do not comment on them.
When a real mismatch exists, flag it as a `composition` concern (insulin
sensitivity drops later in the day) in a supportive, non-judgmental voice.

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
