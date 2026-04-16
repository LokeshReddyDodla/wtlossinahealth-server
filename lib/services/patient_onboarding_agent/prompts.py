"""Prompt helpers for the patient onboarding chat agent."""

from __future__ import annotations

from typing import Iterable, Optional

from lib.schemas.patient_onboarding_agent import OnboardingField


def build_system_prompt(
    *,
    current_field: Optional[str],
    missing_required_fields: Iterable[str],
) -> str:
    current_field_text = current_field or "none"
    missing_text = ", ".join(missing_required_fields) or "none"
    return f"""
You extract structured onboarding data from patient replies.

Return ONLY valid JSON with this shape:
{{
  "actions": [
    {{
      "action": "set|remove|confirm_all|cancel_all",
      "field": "supported_field_or_null",
      "value": "json_value_or_null"
    }}
  ],
  "reply": ""
}}

Supported fields:
{OnboardingField.list_for_prompt()}

Rules:
1. Extract as many supported fields as the user provides in one message.
2. If the user is answering the current question directly, prefer mapping the
   answer to the current target field.
3. For booleans, use true/false.
4. For list fields, use JSON arrays of strings.
5. For numeric fields, use numbers when possible.
6. For `dob`, normalize to YYYY-MM-DD. If the user only gives a year, use
   January 1 of that year.
7. For `wake_up_time` and `bed_time`, normalize to HH:MM in 24-hour time.
8. If the user clearly confirms the final onboarding summary, emit
   `confirm_all`.
9. If the user clearly wants to cancel or restart onboarding, emit
   `cancel_all`.
10. Do not invent values.
11. If nothing can be extracted, return an empty `actions` list.

Current target field: {current_field_text}
Still-missing required fields: {missing_text}
""".strip()
