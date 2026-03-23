# Meal + CGM Playbook

```json
{
  "name": "meal_cgm",
  "applies_to_domains": ["meal", "cgm"],
  "response_modes": ["evaluate", "compare", "recommend"],
  "optional_for_goals": [],
  "enrichments": []
}
```

Use meal-CGM correlation only when the task is evaluative or explicitly asks about impact, spikes, or patterns.
Keep any causality language soft unless the retrieved data clearly supports the pattern.
