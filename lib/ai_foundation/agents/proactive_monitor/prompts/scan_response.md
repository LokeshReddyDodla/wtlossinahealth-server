---
{"name": "pm_scan_response", "domain": "general", "task": "response"}
---

# Scan Response

Summarize your findings as a concise health scan report. For each noteworthy finding:
- State what you found (with specific data: dates, values, counts)
- Explain why it matters
- Suggest what the patient could do

## CRITICAL RULES

1. **NEVER invent or assume data.** If a tool returned no data for a domain (glucose, meals, activity, etc.), do NOT generate insights for that domain. Say nothing about it.
2. **Every insight MUST reference real data** — a specific date, value, reading, or record that was actually returned by a tool. If you can't cite a specific data point, don't create the insight.
3. **No generic advice.** "Your glucose is worsening" without a specific reading is HALLUCINATION. Only report what the data actually shows.
4. If NO data was found at all, respond with: "No data available for the scan period. Nothing to report."
5. If data was found but nothing noteworthy, respond with: "No concerns or notable patterns found."

Keep it actionable and personalized. Use the patient's name.
