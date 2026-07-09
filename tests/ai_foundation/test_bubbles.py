"""Bubble protocol — splitting, stripping, and the streaming sentinel filter."""

from lib.ai_foundation.agents.core.bubbles import (
    BUBBLE_DELIMITER as D,
    BubbleStreamFilter,
    split_bubbles,
    strip_bubbles,
)


class TestSplit:
    def test_no_sentinel_single_bubble(self):
        assert split_bubbles("Just one answer.") == ["Just one answer."]

    def test_basic_split(self):
        text = f"Finding one.\n{D}\nDetail two.\n{D}\nQuestion three?"
        assert split_bubbles(text) == ["Finding one.", "Detail two.", "Question three?"]

    def test_empty_fragments_dropped(self):
        assert split_bubbles(f"{D}\nA\n{D}{D}\nB\n{D}") == ["A", "B"]

    def test_overflow_merged_into_last(self):
        text = D.join(f"part{i}" for i in range(6))
        parts = split_bubbles(text)
        assert len(parts) == 4
        assert "part3" in parts[3] and "part5" in parts[3]

    def test_sentinel_inside_code_fence_repaired(self):
        # model breaks the rule and splits inside a fence — merge preserves it
        text = f"Look:\n```chart-data\na\n{D}\nb\n```\nDone."
        parts = split_bubbles(text)
        assert all(p.count("```") % 2 == 0 for p in parts)

    def test_empty_text(self):
        assert split_bubbles("") == []


class TestStrip:
    def test_passthrough_without_sentinel(self):
        assert strip_bubbles("hello") == "hello"

    def test_strip_joins_with_paragraph_break(self):
        assert strip_bubbles(f"A\n{D}\nB") == "A\n\nB"


class TestStreamFilter:
    def _run(self, chunks):
        f = BubbleStreamFilter()
        out = "".join(f.feed(c) for c in chunks) + f.flush()
        return out

    def test_sentinel_in_one_chunk(self):
        assert self._run([f"A{D}B"]) == "A\n\nB"

    def test_sentinel_split_across_chunks(self):
        assert self._run(["A[[BU", "BBLE]]B"]) == "A\n\nB"

    def test_sentinel_split_char_by_char(self):
        assert self._run(list(f"A{D}B")) == "A\n\nB"

    def test_false_prefix_released(self):
        # "[[B" that never completes must still be emitted
        assert self._run(["A[[B", "old]] text"]) == "A[[Bold]] text"

    def test_trailing_partial_flushed(self):
        assert self._run(["A", "[[BUB"]) == "A[[BUB"

    def test_no_sentinel_passthrough(self):
        assert self._run(["Hello ", "world"]) == "Hello world"

    def test_multiple_sentinels(self):
        assert self._run([f"A{D}B{D}C"]) == "A\n\nB\n\nC"


class TestAwaitMarkers:
    def test_extract_await_basic(self):
        from lib.ai_foundation.agents.core.bubbles import extract_await
        clean, entity = extract_await("Log your lunch and I'll take a look. [[AWAIT:meal]]")
        assert entity == "meal"
        assert "[[AWAIT" not in clean and clean.endswith("look.")

    def test_extract_await_none(self):
        from lib.ai_foundation.agents.core.bubbles import extract_await
        clean, entity = extract_await("Your TIR was 91% this week.")
        assert entity is None and clean == "Your TIR was 91% this week."

    def test_extract_await_first_wins(self):
        from lib.ai_foundation.agents.core.bubbles import extract_await
        clean, entity = extract_await("A [[AWAIT:smbg]] B [[AWAIT:meal]]")
        assert entity == "smbg" and "[[AWAIT" not in clean

    def test_unknown_await_type_passes_through(self):
        from lib.ai_foundation.agents.core.bubbles import extract_await
        clean, entity = extract_await("X [[AWAIT:unicorn]]")
        assert entity is None and "[[AWAIT:unicorn]]" in clean

    def test_stream_filter_swallows_await(self):
        from lib.ai_foundation.agents.core.bubbles import MarkerStreamFilter
        f = MarkerStreamFilter()
        out = "".join(f.feed(c) for c in ["Log it. [[AWA", "IT:meal]]"]) + f.flush()
        assert out == "Log it. "

    def test_stream_filter_bubble_and_await_mixed(self):
        from lib.ai_foundation.agents.core.bubbles import MarkerStreamFilter
        f = MarkerStreamFilter()
        out = f.feed("A[[BUBBLE]]B [[AWAIT:sleep]]") + f.flush()
        assert out == "A\n\nB "
