"""Server-side preview sanitization — single source of truth for the
``last_message_preview`` field that travels in chat_list_updated events
and is persisted on support tickets.

Without this every client (patient, CP, future web) would have to strip
markdown themselves and inevitably diverge.
"""

import pytest

import lib.models  # noqa: F401
from lib.models.patient import Patient  # noqa: F401

from lib.utils.preview import sanitize_preview


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("hello", "hello"),
        ("*bold*", "bold"),
        ("_italic_", "italic"),
        ("`code`", "code"),
        ("~~strike~~", "strike"),
        ("**very bold**", "very bold"),
        ("___emphasis___", "emphasis"),
    ],
)
def test_strips_markdown_formatting_chars(raw, expected):
    assert sanitize_preview(raw) == expected


def test_collapses_whitespace_runs_to_single_space():
    assert sanitize_preview("hello   world\n\nstill   here") == (
        "hello world still here"
    )


def test_trims_leading_trailing_whitespace():
    assert sanitize_preview("   padded   ") == "padded"


def test_truncates_to_max_len_no_ellipsis():
    """Spec says client handles overflow display — server must NOT
    append an ellipsis."""
    out = sanitize_preview("x" * 500)
    assert len(out) == 200
    assert "…" not in out
    assert "..." not in out


def test_custom_max_len_respected():
    out = sanitize_preview("x" * 500, max_len=50)
    assert len(out) == 50


def test_empty_input_returns_empty_string():
    assert sanitize_preview("") == ""
    assert sanitize_preview(None) == ""


def test_preserves_non_markdown_punctuation():
    """Sanitization shouldn't be over-eager: real punctuation in plain
    text (commas, periods, parens, quotes) must survive."""
    raw = 'Yes, "this" is — fine. (really!)'
    assert sanitize_preview(raw) == 'Yes, "this" is — fine. (really!)'


def test_safe_on_unicode_emoji():
    """Healthcare chat content has emoji in it — never mangle."""
    out = sanitize_preview("feeling better 💊 today 🙏")
    assert "💊" in out
    assert "🙏" in out
