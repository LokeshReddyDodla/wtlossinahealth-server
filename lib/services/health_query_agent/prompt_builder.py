from datetime import datetime
from pathlib import Path
from typing import Optional
from string import Template


class PromptBuilder:
    def __init__(self, current_time: Optional[datetime] = None):
        self.current_time: datetime = current_time or datetime.utcnow()
        self._prompts_dir = Path(__file__).parent / "prompts"
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
        if role == "care-provider":
            filename = "system_care_provider.md"
        else:
            filename = "system_patient.md"

        content = self._load_prompt_file(filename)
        return self._render_template(content)

    def get_intent_extraction_prompt(
        self,
        role: str = "patient",
        include_rules: bool = True,
        include_data_definitions: bool = True,
    ) -> str:
        parts = []

        # 1. System prompt (role-specific)
        system_prompt = self.get_system_prompt(role)
        parts.append(system_prompt)

        # 2. Task intent extraction prompt
        task_prompt = self._load_prompt_file("task_intent_extraction.md")
        parts.append(self._render_template(task_prompt))

        # 3. Rules (optional)
        if include_rules:
            rules = self._load_prompt_file("rules.md")
            parts.append(self._render_template(rules))

        # 4. Data definitions (optional)
        if include_data_definitions:
            data_defs = self._load_prompt_file("data_definitions.md")
            parts.append(self._render_template(data_defs))

        return "\n\n---\n\n".join(parts)

    def get_response_prompt(self, user_role: str = "patient") -> str:
        parts = []

        # 1. System prompt (role-specific)
        system_prompt = self.get_system_prompt(user_role)
        parts.append(system_prompt)

        # 2. Task response generation prompt
        response_prompt = self._load_prompt_file("task_response_generation.md")
        parts.append(self._render_template(response_prompt))

        return "\n\n---\n\n".join(parts)

    def get_raw_prompt(self, filename: str, **kwargs) -> str:
        content = self._load_prompt_file(filename)
        return self._render_template(content, **kwargs)

    def clear_cache(self):
        """Clear the prompt cache (useful for hot-reloading during development)."""
        self._cache.clear()
