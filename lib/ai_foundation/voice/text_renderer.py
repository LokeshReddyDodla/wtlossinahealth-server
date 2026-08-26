from __future__ import annotations

from typing import Protocol

from markdown_it import MarkdownIt
from markdown_it.token import Token


class SpeechTextRenderer(Protocol):
    def render(self, text: str) -> str: ...


class MarkdownSpeechTextRenderer:
    def __init__(self) -> None:
        self._parser = MarkdownIt("commonmark", {"html": False})

    def render(self, text: str) -> str:
        blocks: list[str] = []
        for token in self._parser.parse(text):
            if token.type == "inline":
                content = self._inline_text(token.children or [])
            elif token.type in {"code_block", "fence"}:
                content = token.content
            else:
                continue
            content = content.strip()
            if content:
                blocks.append(content)
        return "\n".join(blocks)

    @staticmethod
    def _inline_text(tokens: list[Token]) -> str:
        parts: list[str] = []
        for token in tokens:
            if token.type in {"text", "code_inline", "image"}:
                parts.append(token.content)
            elif token.type in {"softbreak", "hardbreak"}:
                parts.append("\n")
        return "".join(parts)
