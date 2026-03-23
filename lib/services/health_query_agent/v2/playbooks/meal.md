# Meal Playbook

```json
{
  "name": "meal",
  "applies_to_domains": ["meal"],
  "response_modes": ["list", "summarize", "evaluate", "recommend"],
  "optional_for_goals": [],
  "enrichments": ["cgm", "fitness"]
}
```

Prefer meal-specific synthesis over repeating every logged item unless the user explicitly asked to list meals.
For `list`, keep the answer factual and compact.
For `evaluate`, look at meal count, timing, calories, protein, carbs, fats, fiber, consistency, and repeated patterns.
Only bring in glucose or fitness context when the task is evaluative or comparative, not when the user simply asks to show meals.
