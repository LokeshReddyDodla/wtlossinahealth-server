from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable, List

from pydantic import BaseModel, Field

from .models import DomainName, ResponseMode


class Playbook(BaseModel):
    name: str
    applies_to_domains: List[DomainName] = Field(default_factory=list)
    response_modes: List[ResponseMode] = Field(default_factory=list)
    optional_for_goals: List[str] = Field(default_factory=list)
    enrichments: List[DomainName] = Field(default_factory=list)
    body: str


class PlaybookLoader:
    def __init__(self, playbooks_dir: Path | None = None):
        self.playbooks_dir = playbooks_dir or Path(__file__).parent / "playbooks"

    @lru_cache(maxsize=1)
    def load_all(self) -> List[Playbook]:
        playbooks: List[Playbook] = []
        for path in sorted(self.playbooks_dir.glob("*.md")):
            playbooks.append(self._load_playbook(path))
        return playbooks

    def load_by_name(self, name: str) -> Playbook | None:
        for playbook in self.load_all():
            if playbook.name == name:
                return playbook
        return None

    def select(
        self,
        domains: Iterable[DomainName],
        response_mode: ResponseMode,
        goal: str | None = None,
    ) -> List[Playbook]:
        domain_set = set(domains)
        selected: List[Playbook] = []
        for playbook in self.load_all():
            if playbook.applies_to_domains and not (domain_set & set(playbook.applies_to_domains)):
                continue
            if playbook.response_modes and response_mode not in playbook.response_modes:
                continue
            if goal and playbook.optional_for_goals and goal.lower() not in {
                g.lower() for g in playbook.optional_for_goals
            }:
                continue
            selected.append(playbook)
        return selected

    def _load_playbook(self, path: Path) -> Playbook:
        content = path.read_text(encoding="utf-8")
        metadata = self._extract_metadata(content)
        body = self._strip_first_json_block(content).strip()
        return Playbook(body=body, **metadata)

    @staticmethod
    def _extract_metadata(content: str) -> dict:
        match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
        if not match:
            raise ValueError("Playbook metadata block missing")
        return json.loads(match.group(1))

    @staticmethod
    def _strip_first_json_block(content: str) -> str:
        return re.sub(r"```json\s*\{.*?\}\s*```", "", content, count=1, flags=re.DOTALL)
