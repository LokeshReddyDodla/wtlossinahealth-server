# SMBG Playbook

```json
{
  "name": "smbg",
  "applies_to_domains": ["smbg"],
  "response_modes": ["list", "summarize", "evaluate", "compare"],
  "optional_for_goals": [],
  "enrichments": ["meal"]
}
```

Use SMBG readings as discrete fingerstick evidence. Keep date and reading context clear.
If meal-window framing is available, mention it only when it helps answer the user's question.
