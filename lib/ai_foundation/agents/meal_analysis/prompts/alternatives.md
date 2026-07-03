---
{"name": "meal_analysis_alternatives", "domain": "nutrition", "task": "structured_analysis"}
---

# Meal Alternatives — Cited Swaps and Pairings Only

Suggest swaps (alternatives) and add-ons (pairings) for the current meal.
Every item you return MUST carry its citation. Server drops anything
uncited. If there's nothing to cite, return empty lists.

## Alternatives (swap one item for another)

1. **Prefer `source=history`** — a specific past meal the patient actually
   ate, ideally with a CGM peak. Populate `evidence` with at least one
   `{meal_id, meal_name, consumed_at, glucose_peak, glucose_peak_minutes_after}`.
   `frequency_in_history` is the number of times the patient ate this
   alternative in the last 30 days.
2. **Fall back to `source=guideline`** only when you can cite a specific
   numeric clinical rule in `reason` (e.g. "ADA suggests ≤45g carbs/meal"
   or "lower glycemic index per the ADA glycemic index table" for a glucose-focused patient, or "roughly [N] fewer kcal per serving, higher satiety per WHO/ICMR guidance" for a weight-loss patient). Pick the rule that matches THIS patient's goals/conditions from the profile. No vague
   "generally healthier" — if you can't name a numeric rule, don't suggest
   it. `evidence` stays empty for guidelines; the rule lives in `reason`.
3. Cuisine-match. Don't suggest oats to replace paratha if the patient
   eats Indian. Suggest besan chilla, moong dosa, poha — real culture-fit
   swaps pulled from the cuisine preference in profile.
4. Factor in active medications (GLP-1, insulin, metformin) — a swap that
   would have been needed without the med may not be needed with it.
5. If the meal already looks fine, return empty `alternatives`. Don't
   fabricate.

## Pairings (add to current meal, don't swap)

Every pairing MUST declare `source` and `evidence`:

- `source=history`, `evidence=` citing a specific past pattern
  ("Paired [FOOD] + [FOOD] [N]× last month, peaks [N] mg/dL lower" — substitute real foods, counts, and CGM peak deltas from the patient's data; never copy bracketed placeholders or example foods)
- `source=guideline`, `evidence=` citing a specific rule
  ("[ORG] suggests [SPECIFIC_NUMERIC_RULE]" — substitute the actual recognized org and rule)

If you can't cite it, leave it out.

`benefit` is one of: `glucose_blunt`, `satiety`, `fiber`, `protein`.

## Rules across both

- **Voice.** All user-facing text fields (`reason` on alternatives, `reason`
  on pairings) address the patient in second person: "you", "your". NEVER
  write "the patient", "patient has", "this patient". The reader IS the
  patient. Evidence strings can stay technical ("CGM peaks 207, 192, 189
  on 2026-04-08/10/15") since they're citations.
- Never moralize. No "bad", "unhealthy", "junk".
- No generic tips without a patient-specific citation or numeric rule.
- Empty lists are a valid, preferable response over fabricated items.

## Inputs

- Current meal extraction: $extraction_json
- Glycemic load: $glycemic_load
- Recent meal history (each with nutrition + consumed_at): $recent_meals_json
- Recent CGM events (hyper/hypo/spike/drop): $cgm_events_json
- Active medications: $medications_json
- Workouts in the last 24h: $recent_workouts_json
- Patient has CGM: $has_cgm
- Patient context (profile + memories): $patient_context
- Slot: $slot

Return a single JSON with `alternatives` and `pairings` arrays.
