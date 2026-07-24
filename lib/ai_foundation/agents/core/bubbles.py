"""Companion message markers: multi-bubble protocol + data-request markers.

The responder LLM may emit two kinds of structural markers, both invisible
to users:

- ``[[BUBBLE]]`` — natural message break (2-4 bubbles per turn)
- ``[[AWAIT:<entity>]]`` — the reply explicitly invited the user to LOG the
  named entity (meal, smbg, ...); the server records a pending data request
  so the eventual log can continue this conversation (companion Phase 3).

API:
- ``split_bubbles`` / ``strip_bubbles`` — final-text handling
- ``extract_await`` — pull the awaited entity type out of the raw text
- ``MarkerStreamFilter`` — removes all markers from token deltas mid-stream,
  holding back only potential marker prefixes at chunk boundaries

Design notes: the prompt instructs the model to place markers between
paragraphs / at the end and never inside code fences; the splitter still
repairs fence breakage defensively (a bubble with an unclosed ``` is merged
with the next) because prompt rules are advisory, not guarantees.
"""

from __future__ import annotations

import re

BUBBLE_DELIMITER = "[[BUBBLE]]"

# Entity types the agent may ask the user to log. MUST stay a subset of the
# event triggers that actually enqueue handle_proactive_event (meal + smbg
# vector tasks, symptom via daily_checkin_service) — an AWAIT for an entity
# with no producer is a promise the system can never keep: the user logs it
# and nothing ever replies. Add sleep/mood/workout ONLY with their triggers.
AWAIT_ENTITY_TYPES = ("meal", "smbg", "symptom")

_AWAIT_RE = re.compile(r"\[\[AWAIT:(" + "|".join(AWAIT_ENTITY_TYPES) + r")\]\]")
# Strip ANY await-shaped marker (incl. hallucinated entities) from user-visible
# text; only known entities count for the pending-request decision.
_AWAIT_ANY_RE = re.compile(r"\[\[AWAIT:[a-z_]+\]\]")

# marker → visible replacement
_MARKERS: dict[str, str] = {BUBBLE_DELIMITER: "\n\n"}
_MARKERS.update({f"[[AWAIT:{e}]]": "" for e in AWAIT_ENTITY_TYPES})

_MAX_BUBBLES = 4


def extract_await(text: str) -> tuple[str, str | None]:
    """Strip AWAIT markers; return (clean_text, awaited_entity_type|None).

    Multiple markers: first entity wins (one pending request per turn).
    """
    if not text or "[[AWAIT:" not in text:
        return text, None
    match = _AWAIT_RE.search(text)
    entity = match.group(1) if match else None
    return _AWAIT_ANY_RE.sub("", text).strip(), entity


def _fence_balanced(text: str) -> bool:
    return text.count("```") % 2 == 0


def split_bubbles(text: str) -> list[str]:
    """Split responder output into clean bubble strings.

    Merges any split that would break a ``` fence, drops empty fragments,
    and joins overflow beyond _MAX_BUBBLES into the last bubble.
    """
    if not text:
        return []
    parts = [p.strip() for p in text.split(BUBBLE_DELIMITER)]
    parts = [p for p in parts if p]

    merged: list[str] = []
    for part in parts:
        if merged and not _fence_balanced(merged[-1]):
            merged[-1] = merged[-1] + "\n\n" + part
        else:
            merged.append(part)

    if len(merged) > _MAX_BUBBLES:
        head, tail = merged[: _MAX_BUBBLES - 1], merged[_MAX_BUBBLES - 1 :]
        merged = head + ["\n\n".join(tail)]
    return merged


def strip_bubbles(text: str) -> str:
    """One clean string for legacy single-bubble rendering."""
    if not text:
        return text
    return "\n\n".join(split_bubbles(text)) if BUBBLE_DELIMITER in text else text


class MarkerStreamFilter:
    """Removes all known markers from a stream of text deltas.

    Markers may arrive split across chunk boundaries, so the filter holds
    back the longest suffix of pending text that is a prefix of any marker
    until it can be classified.
    """

    def __init__(self) -> None:
        self._held = ""

    def feed_events(self, delta: str) -> list[tuple[str, str]]:
        """Classify a delta into ordered events: ("text", chunk) and
        ("bubble", "") boundary markers. AWAIT markers are silently dropped.

        Lets the streaming pipeline emit a dedicated bubble-boundary SSE
        event so clients can finalize the current bubble and stream the next
        one live — no end-of-turn reorganization under the reader's eyes.
        """
        buf = self._held + delta
        self._held = ""  # absorbed into buf; re-set only when holding a new suffix
        events: list[tuple[str, str]] = []

        def emit_text(chunk: str) -> None:
            if chunk:
                events.append(("text", chunk))

        while buf:
            # earliest known marker in the buffer
            first_idx, first_marker = -1, None
            for marker in _MARKERS:
                idx = buf.find(marker)
                if idx != -1 and (first_idx == -1 or idx < first_idx):
                    first_idx, first_marker = idx, marker
            if first_marker is not None:
                emit_text(buf[:first_idx])
                if first_marker == BUBBLE_DELIMITER:
                    events.append(("bubble", ""))
                buf = buf[first_idx + len(first_marker):]
                continue
            # hold back a trailing partial marker, emit the rest
            hold = 0
            max_check = min(len(buf), max(len(m) for m in _MARKERS) - 1)
            for k in range(max_check, 0, -1):
                suffix = buf[-k:]
                if any(m.startswith(suffix) for m in _MARKERS):
                    hold = k
                    break
            if hold:
                emit_text(buf[:-hold])
                self._held = buf[-hold:]
            else:
                emit_text(buf)
            buf = ""
        return events

    def feed(self, delta: str) -> str:
        """Flat variant: markers removed; bubble boundaries become paragraph
        breaks. Kept for callers that need a single visible string."""
        out: list[str] = []
        for kind, chunk in self.feed_events(delta):
            out.append("\n\n" if kind == "bubble" else chunk)
        return "".join(out)

    def flush(self) -> str:
        held, self._held = self._held, ""
        # Text is only ever held because it's a marker prefix — if the stream
        # truncated mid-marker, emitting "[[AWAIT:me" would flash raw
        # protocol text at the user. The done-payload reconciliation still
        # has the raw response, so dropping the fragment loses nothing.
        if held and any(m.startswith(held) for m in _MARKERS):
            return ""
        return held


# Backward-compatible alias (Phase 1 name)
BubbleStreamFilter = MarkerStreamFilter
