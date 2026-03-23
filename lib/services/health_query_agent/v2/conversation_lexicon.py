from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field


class ConversationLexicon(BaseModel):
    greetings: set[str] = Field(default_factory=set)
    acknowledgements: set[str] = Field(default_factory=set)
    goal_aliases: dict[str, str] = Field(default_factory=dict)
    date_aliases: dict[str, str] = Field(default_factory=dict)
    domain_keywords: dict[str, list[str]] = Field(default_factory=dict)


class ConversationLexiconLoader:
    def __init__(self, path: Path | None = None):
        self.path = path or Path(__file__).with_name("conversation_lexicon.json")

    @lru_cache(maxsize=1)
    def load(self) -> ConversationLexicon:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return ConversationLexicon(
            greetings={item.lower() for item in payload.get("greetings", [])},
            acknowledgements={
                item.lower() for item in payload.get("acknowledgements", [])
            },
            goal_aliases={
                key.lower(): value for key, value in payload.get("goal_aliases", {}).items()
            },
            date_aliases={
                key.lower(): value for key, value in payload.get("date_aliases", {}).items()
            },
            domain_keywords={
                key: [value.lower() for value in values]
                for key, values in payload.get("domain_keywords", {}).items()
            },
        )
