# CGM Playbook

```json
{
  "name": "cgm",
  "applies_to_domains": ["cgm"],
  "response_modes": ["summarize", "evaluate", "compare", "recommend"],
  "optional_for_goals": [],
  "enrichments": ["meal"]
}
```

For CGM responses, prioritize average glucose, time in range, variability, and important event patterns.
Correlate with meals only when the user asks for analysis, causality, or optimization.
