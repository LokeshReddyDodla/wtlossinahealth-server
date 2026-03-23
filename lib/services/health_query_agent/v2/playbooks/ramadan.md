# Ramadan Playbook

```json
{
  "name": "ramadan",
  "applies_to_domains": ["meal", "fitness"],
  "response_modes": ["summarize", "evaluate", "recommend"],
  "optional_for_goals": [],
  "enrichments": []
}
```

When fasting context is known, interpret meal timing around suhoor and iftar instead of daytime meal assumptions.
Be careful not to repeat Ramadan context in every turn unless it affects the current answer.
