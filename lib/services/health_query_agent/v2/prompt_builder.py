from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from string import Template
from typing import Optional


class PromptBuilder:
    def __init__(self, current_time: Optional[datetime] = None):
        self.current_time: datetime = current_time or datetime.now(UTC)
        self._prompts_dir = Path(__file__).resolve().parent.parent / "prompts"
        self._cache: dict[str, str] = {}

    def _load_prompt_file(self, filename: str) -> str:
        if filename in self._cache:
            return self._cache[filename]

        filepath = self._prompts_dir / filename
        if not filepath.exists():
            raise FileNotFoundError(f"Prompt file not found: {filepath}")

        content = filepath.read_text(encoding="utf-8")
        self._cache[filename] = content
        return content

    def _render_template(self, content: str, **kwargs) -> str:
        template = Template(content)
        template_vars = {"current_time": self.current_time.isoformat(), **kwargs}
        return template.safe_substitute(template_vars)

    def get_system_prompt(self, role: str = "patient") -> str:
        filename = "system_care_provider.md" if role == "care-provider" else "system_patient.md"
        content = self._load_prompt_file(filename)
        return self._render_template(content)

    def get_intent_extraction_prompt(
        self,
        role: str = "patient",
        include_rules: bool = True,
        include_data_definitions: bool = True,
    ) -> str:
        parts = [self.get_system_prompt(role), self._render_template(self._load_prompt_file("task_intent_extraction.md"))]
        if include_rules:
            parts.append(self._render_template(self._load_prompt_file("rules.md")))
        if include_data_definitions:
            parts.append(self._render_template(self._load_prompt_file("data_definitions.md")))
        return "\n\n---\n\n".join(parts)

    def get_response_prompt(self, user_role: str = "patient") -> str:
        parts = [
            self.get_system_prompt(user_role),
            self._render_template(self._load_prompt_file("task_response_generation.md")),
        ]
        return "\n\n---\n\n".join(parts)

    def get_raw_prompt(self, filename: str, **kwargs) -> str:
        return self._render_template(self._load_prompt_file(filename), **kwargs)

    def clear_cache(self):
        self._cache.clear()
