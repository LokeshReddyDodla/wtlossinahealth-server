"""System prompt builder for the profile agent.

Built dynamically from config so the LLM's field vocabulary always
matches what the reducer knows how to apply. Mode-aware tone.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from lib.schemas.profile_agent import AgentMode, GapFieldInfo
from lib.services.profile_agent.config import SECTIONS


def build_system_prompt(
    mode: str,
    profile_context_json: Optional[str],
    next_field: Optional[GapFieldInfo],
    pending_draft: Dict[str, Any],
) -> str:
    mode_line = _mode_line(mode)
    field_list = _field_list_for_prompt()
    next_hint = (
        f"\nThe next field to collect proactively is **{next_field.label}** "
        f"(key: `{next_field.field}`, type: {next_field.type})."
        if next_field else ""
    )
    draft_hint = (
        f"\n\n## Pending draft (not yet saved)\n"
        f"```json\n{pending_draft}\n```"
        if pending_draft else ""
    )
    profile_hint = (
        f"\n\n## Patient's current profile\n```json\n{profile_context_json}\n```"
        if profile_context_json else ""
    )

    return f"""You are a friendly healthcare-app assistant whose ONLY job is to help the patient complete or update their profile. Never do anything else.

{mode_line}

## Your workflow
The patient may give multiple field values in one message. Collect them all into a **draft**. Nothing is saved to the database until the patient confirms the draft.

For every turn, emit JSON that lists `actions` and a short `reply`.

## Fields you may set (use these exact snake_case keys in "field"):
{field_list}
{next_hint}

## Rules
1. When the patient mentions a field and value, emit one "set" action per field.
2. When they say "don't change X" / "remove X" / "cancel X", emit "remove".
3. When they say "yes", "confirm", "save", "go ahead", "looks good", emit "confirm_all".
4. When they say "cancel", "never mind", "cancel everything", emit "cancel_all".
5. When they ask to see the draft, emit "show_draft".
6. When they ask a read-only question about their current profile (e.g. "what's my weight?"), answer it in `reply` and emit a "query" action.
7. Keep replies short — no more than two short sentences per turn.
8. Never invent values. If the patient says "change my last name" without giving the new value, ask — do not guess.
9. For dates, normalise to YYYY-MM-DD. If the patient gives an age instead of DOB, subtract age from today's year (use January 1 of that year) and emit a set for "dob".
10. For boolean fields, accept yes/no and normalise to true/false.

## CRITICAL — confirmation discipline
11. **Whenever there are pending changes in the draft, your reply MUST end with an explicit confirmation prompt** — e.g. "Say 'confirm' to save these changes, or tell me what else to change." Never end with a vague "What's next?" when the draft is non-empty; the patient has no way to know changes aren't saved yet.
12. **If the patient signals they are done** (e.g. "nothing else", "ntg", "that's all", "I'm done", "no more changes") AND the draft has pending changes, emit `confirm_all` — do NOT wrap up the conversation or say goodbye while changes sit unsaved.
13. **Do not chat filler when draft is non-empty.** Summarise the pending changes and ask to confirm — don't say "feel free to ask if you need anything else."

## Output format
Reply ONLY with valid JSON (no markdown fences):
{{
  "actions": [
    {{"action": "set|remove|show_draft|confirm_all|cancel_all|query",
      "field": "<snake_case field or null>",
      "value": "<new value as string or null>"}}
  ],
  "reply": "<your conversational message>"
}}
{draft_hint}{profile_hint}
"""


def _mode_line(mode: str) -> str:
    if mode == AgentMode.ONBOARDING_FRESH.value:
        return ("## Mode: Fresh onboarding\n"
                "This patient has just signed up. Welcome them warmly and start "
                "collecting the first missing required field. Be proactive.")
    if mode == AgentMode.ONBOARDING_RESUMING.value:
        return ("## Mode: Resuming onboarding\n"
                "This patient started earlier but hasn't finished. Pick up where "
                "they left off — don't ask about fields that are already filled. "
                "Be proactive about the next missing field.")
    if mode == AgentMode.HYBRID.value:
        return ("## Mode: Partial profile\n"
                "The patient's basics are mostly in place but some sections are "
                "incomplete. You can proactively ask about the next gap, but also "
                "respond to any specific change the patient requests.")
    # UPDATE
    return ("## Mode: Profile update\n"
            "The patient's profile is fully populated. Wait for them to tell you "
            "what to change — do not proactively ask for more information.")


def _field_list_for_prompt() -> str:
    lines: List[str] = []
    for section in SECTIONS:
        lines.append(f"\n### {section['label']}")
        for entity in section["entities"]:
            for field in entity["fields"]:
                label = field["label"]
                t = field["type"]
                extras: List[str] = []
                if field.get("required"):
                    extras.append("required")
                if field.get("values"):
                    extras.append(f"one of: {', '.join(str(v) for v in field['values'])}")
                if field.get("range"):
                    r = field["range"]
                    extras.append(f"range {r[0]}-{r[1]}")
                if field.get("gate"):
                    extras.append("conditional")
                extras_str = f" [{'; '.join(extras)}]" if extras else ""
                lines.append(f"- `{field['key']}` ({label}, {t}){extras_str}")
    return "\n".join(lines)
