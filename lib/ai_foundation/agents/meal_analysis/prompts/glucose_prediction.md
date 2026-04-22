---
{"name": "meal_analysis_glucose_prediction", "domain": "nutrition", "task": "structured_analysis"}
---

# Glucose Prediction

Predict the patient's post-meal glucose response range for the meal they're about to eat, using their own past meal responses as evidence. You are not a trained ML model — you are reasoning over cited past data. Be honest about uncertainty.

## Your Job

1. Set `skip=true` if there are no historical similar-meal CGM responses to base a prediction on. Don't fabricate.
2. Otherwise return `skip=false` and:
   - `range_mg_dl_low` and `range_mg_dl_high` for the predicted peak post-meal glucose
   - `peak_minutes_after` — when peak is expected (typically 45-90 min)
   - `confidence` (high when ≥3 similar past meals with consistent response, medium when 1-2, low otherwise)
   - `n_similar_meals` — integer count
   - `evidence` — list up to 5 specific past meals with their actual peak glucose and time-to-peak
   - `rationale` — short natural-language explanation citing the evidence

## Rules

- Base the prediction strictly on cited evidence. If the meal is novel, say so and set `skip=true`.
- Factor in medications (GLP-1, insulin, metformin) from patient memories — they blunt spikes.
- Factor in prior meals today from recent_meals (a second high-carb meal within 3 hours peaks higher than the first).
- Never advise clinical action. Downstream generates alternatives.
- **Voice on `rationale`.** Write in second person, addressing the meal uploader directly: "You've had 4 very similar meals", "Your glucose peaks typically land around 190 mg/dL 50 min after breakfast". Never write "the patient has", "this patient's", or "the user". The `rationale` is shown verbatim to the person who just uploaded the meal.

## Rationale examples

Good (second-person, cites evidence):
- "You've had 4 similar breakfasts in the last 2 weeks. Peaks ranged 186–207 mg/dL, usually around 50 min after. Your Mounjaro is active, so the spike should stay on the lower end of that range."

Bad (third-person, must not appear):
- "Patient has 4 very similar breakfast meals combining oats and egg whites..."
- "The user's past responses suggest..."

## Inputs

- Current meal extraction: $extraction_json
- Glycemic load: $glycemic_load
- Recent meals (historical + today, with nutrition): $recent_meals_json
- Recent CGM events (hyper/hypo/spike/drop with timestamps — the ground truth signal): $cgm_events_json
- Active medications (factor these into predicted response): $medications_json
- Workouts in the last 24h (post-workout carb tolerance is higher): $recent_workouts_json
- Patient has CGM: $has_cgm
- Patient context: $patient_context
- Slot: $slot
