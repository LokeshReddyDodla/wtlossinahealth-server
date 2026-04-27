"""Pure FSM transitions for the profile-agent draft.

States: COLLECTING → REVIEWING → COMPLETED
              ↓           ↓
           CANCELLED   COLLECTING (on validation failure)

No APPLYING state — apply is a transient phase inside the
REVIEWING → COMPLETED transition.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from lib.schemas.profile_agent import DraftState, LLMAction
from lib.services.profile_agent.config import (
    ALL_FIELD_KEYS,
    FIELD_TO_CONFIG,
    FIELD_TO_SECTION,
    fields_with_user_provided_value,
)

# Sections whose fields are never skippable. Even an optional field in
# these sections must hold a real value (no "idk", "n/a", etc.) before
# it can land in the draft.
_NEVER_SKIP_SECTIONS = {"basic"}

# Reducer signals
SIG_CONTINUE = "continue"
SIG_REVIEW = "review"
SIG_CANCEL = "cancel"

# Sentinel strings the LLM sometimes emits when the user said "idk".
# Required fields must hold a real, typed value — these placeholders
# would mask the gap and let the agent skip past mandatory questions.
_PLACEHOLDER_VALUES = {
    "idk", "i don't know", "i dont know", "dont know", "don't know",
    "unknown", "unsure", "not sure", "no idea", "n/a", "na",
    "skip", "pass", "none", "null", "-", "?",
}


def reduce_draft(
    draft_changes: Dict[str, Any],
    actions: List[LLMAction],
    user_messages_text: str = "",
) -> Tuple[Dict[str, Any], str, List[str]]:
    """Apply a list of LLM actions to the draft.

    Returns (updated_draft, signal, dropped_field_names).

    `dropped_field_names` are fields where the LLM's value looked
    hallucinated (see fields_with_user_provided_value) — caller can
    use them to craft a "what would you like to set X to?" reply.
    """
    dropped: List[str] = []
    signal = SIG_CONTINUE
    hallucination_fields = fields_with_user_provided_value()
    lowered_messages = user_messages_text.lower()

    for act in actions:
        atype = act.action
        field = act.field
        value = act.value

        if atype == "set":
            if not field or field not in ALL_FIELD_KEYS:
                continue
            if value is None or (isinstance(value, str) and value.strip() == ""):
                continue
            if isinstance(value, str) and value.strip().lower() in _PLACEHOLDER_VALUES:
                # User said "idk"/"skip" and the LLM tried to set a sentinel
                # value. Drop it so the field stays flagged as missing.
                cfg = FIELD_TO_CONFIG.get(field, {})
                if (
                    cfg.get("required")
                    or cfg.get("type") not in ("string", "list_of_string")
                    or FIELD_TO_SECTION.get(field) in _NEVER_SKIP_SECTIONS
                ):
                    continue
            if (
                field in hallucination_fields
                and isinstance(value, str)
                and value.lower() not in lowered_messages
            ):
                dropped.append(field)
                continue
            draft_changes[field] = value

        elif atype == "remove":
            if not field:
                continue
            draft_changes.pop(field, None)

        elif atype == "confirm_all":
            signal = SIG_REVIEW

        elif atype == "cancel_all":
            draft_changes.clear()
            signal = SIG_CANCEL

        # "show_draft" and "query" are no-ops on draft state.

    return draft_changes, signal, dropped


def next_state_on_cancel() -> DraftState:
    return DraftState.CANCELLED


def next_state_on_apply_success() -> DraftState:
    return DraftState.COMPLETED


def next_state_on_validation_error() -> DraftState:
    """Bounce back to COLLECTING so the user can fix values."""
    return DraftState.COLLECTING
