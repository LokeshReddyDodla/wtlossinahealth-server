"""Multi-bubble message protocol.

The responder LLM separates natural message breaks with a sentinel line
(``[[BUBBLE]]``). Old clients must never see the literal, so:

- ``split_bubbles``  → the final text as 1-4 clean bubble strings
- ``strip_bubbles``  → the final text as one clean string (legacy rendering)
- ``BubbleStreamFilter`` → removes sentinels from token deltas mid-stream,
  holding back only a potential sentinel prefix at chunk boundaries

Design notes: the prompt instructs the model to place the sentinel between
paragraphs and never inside code fences; the splitter still repairs fence
breakage defensively (a bubble with an unclosed ``` is merged with the next)
because prompt rules are advisory, not guarantees.
"""

from __future__ import annotations

BUBBLE_DELIMITER = "[[BUBBLE]]"

_MAX_BUBBLES = 4


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


class BubbleStreamFilter:
    """Removes sentinel occurrences from a stream of text deltas.

    The sentinel may arrive split across chunk boundaries, so the filter
    holds back the longest suffix of emitted text that is a prefix of the
    sentinel until it can be classified.
    """

    def __init__(self) -> None:
        self._held = ""

    def feed(self, delta: str) -> str:
        buf = self._held + delta
        self._held = ""  # absorbed into buf; re-set only when holding a new suffix
        out: list[str] = []
        while buf:
            idx = buf.find(BUBBLE_DELIMITER)
            if idx != -1:
                out.append(buf[:idx])
                # sentinel becomes a paragraph break in the visible stream
                out.append("\n\n")
                buf = buf[idx + len(BUBBLE_DELIMITER):]
                continue
            # hold back a trailing partial sentinel, emit the rest
            hold = 0
            max_check = min(len(buf), len(BUBBLE_DELIMITER) - 1)
            for k in range(max_check, 0, -1):
                if BUBBLE_DELIMITER.startswith(buf[-k:]):
                    hold = k
                    break
            if hold:
                out.append(buf[:-hold])
                self._held = buf[-hold:]
            else:
                out.append(buf)
                self._held = ""
            buf = ""
        return "".join(out)

    def flush(self) -> str:
        held, self._held = self._held, ""
        return held
