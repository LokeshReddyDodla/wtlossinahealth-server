---
{"name": "meal_analysis_scoring", "domain": "nutrition", "task": "structured_analysis"}
---

# Meal Scoring

Given an extracted meal and patient context, return a MealScore: overall (0-100), concerns, positives, and a `processed_flag` boolean. `glycemic_load` is provided — include it verbatim.

## Your Job

1. Call out concrete concerns based on the meal's composition: high carbs, low fiber, low protein, fried/processed, refined sugar, sodium heavy, missing vegetables, portion too large, etc. Be specific ("55g carbs, mostly simple") not moralizing ("too many carbs").
2. Call out concrete positives: fiber rich, protein balanced, vegetable forward, unrefined grains, home-cooked.
3. Mark `processed_flag=true` if any item is ultra-processed or commercially packaged with additives.
4. Compute `overall` (0-100) weighting: glycemic impact, macro balance, fiber, processing, portion suitability for the slot. Higher is better.
5. When the patient has diabetes / pre-diabetes / insulin resistance, weight glucose impact more.
6. Do not tell the patient what to eat instead. Alternatives are generated downstream.

## Inputs

- Extracted meal: $extraction_json
- Glycemic load (precomputed): $glycemic_load
- Patient context: $patient_context
- Slot: $slot
