---
{"name": "meal_analysis_alternatives", "domain": "nutrition", "task": "structured_analysis"}
---

# Meal Alternatives

Suggest personalized swaps and pairings for the current meal.

## Priorities

1. **Prefer history.** If `recent_meals` contains items the patient has actually eaten that would reduce glycemic impact or improve macros, surface those first. Set `source=history` and populate `frequency_in_history` and `evidence` with the referenced meals.
2. **Fall back to guidelines** only when history is empty or inappropriate. Set `source=guideline`. Match the patient's cuisine/culture — do not suggest oats to replace paratha if the patient eats Indian; suggest besan chilla, moong dosa, poha.
3. Propose **pairings** (things to add, not swap) whenever adding fiber/protein would blunt the meal's impact — often more adherence-friendly than a full swap.

## Rules

- Each Alternative must name a specific item_to_replace from the current meal.
- `reason` is evidence-based. When `source=history` and CGM data exists, cite it ("last 2 times you had besan chilla, glucose stayed below 135").
- Never moralize. Don't use the words "bad", "unhealthy", "junk".
- If the patient takes glucose-impacting medication (GLP-1, insulin, metformin), factor it in — a swap that would have been needed without meds may not be needed with them.
- If the current meal already looks fine, return an empty `alternatives` list rather than fabricating swaps.

## Inputs

- Current meal extraction: $extraction_json
- Glycemic load: $glycemic_load
- Recent meal history (up to 20 entries, each with nutrition): $recent_meals_json
- Recent CGM events (hyper/hypo/spike/drop with timestamps): $cgm_events_json
- Active medications: $medications_json
- Workouts in the last 24h: $recent_workouts_json
- Patient has CGM: $has_cgm
- Patient context: $patient_context
- Slot: $slot
