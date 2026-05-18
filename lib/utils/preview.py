"""Server-side preview sanitization for chat_list_updated payloads.

Single source of truth — patient app, CP app, and any future web client
all consume the same sanitized preview. Without this each client would
have to strip markdown themselves and inevitably diverge.

Per the unified event contract (spec item A):
- plain text only — strip markdown formatting characters
- collapse runs of whitespace (newlines, tabs) to single spaces
- truncate to ``max_len`` chars, no ellipsis (client handles overflow)
"""

import re

# Stripped: * _ ` ~ — covers bold/italic/code/strikethrough markdown.
# We intentionally don't try to parse markdown structure (links, headers)
# because chat content is typed prose, not formatted markdown documents.
_MD_FORMATTING_CHARS = re.compile(r"[*_`~]+")
_WHITESPACE_RUN = re.compile(r"\s+")


def sanitize_preview(content: str | None, max_len: int = 200) -> str:
    """Return a plain-text, single-line, truncated preview safe for any
    chat-list UI. Empty string for None/empty input."""
    if not content:
        return ""
    text = _MD_FORMATTING_CHARS.sub("", content)
    text = _WHITESPACE_RUN.sub(" ", text).strip()
    return text[:max_len]
