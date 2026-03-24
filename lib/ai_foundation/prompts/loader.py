"""
Prompt Loader — loads prompt templates from markdown files with optional
JSON front-matter metadata.

File format::

    ---
    {
      "name": "system_patient",
      "version": "1.2.0",
      "domain": "general",
      "task": "system",
      "role": "patient"
    }
    ---

    You are a helpful health assistant...

Files without front-matter are loaded with metadata inferred from the
filename (e.g. ``system_patient.md`` → name="system_patient").
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from string import Template

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_FRONT_MATTER_RE = re.compile(
    r"^\s*---\s*\n(.*?)\n\s*---\s*\n",
    re.DOTALL,
)


class PromptMeta(BaseModel):
    """Metadata for a prompt template."""

    model_config = {"protected_namespaces": ()}

    name: str = Field(..., description="Unique prompt name, e.g. 'system_patient'.")
    version: str = Field(default="1.0.0", description="SemVer version string.")
    domain: str | None = Field(
        default=None,
        description="Health domain: 'cgm', 'meal', 'fitness', 'sleep', etc.",
    )
    task: str | None = Field(
        default=None,
        description="Task type: 'intent_extraction', 'response', 'playbook', 'system'.",
    )
    role: str | None = Field(
        default=None,
        description="Target role: 'patient', 'care_provider'.",
    )
    model_hint: str | None = Field(
        default=None,
        description="Suggested model for this prompt, e.g. 'gpt-4.1-mini'.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Arbitrary tags for filtering.",
    )


class PromptTemplate(BaseModel):
    """A loaded prompt with metadata, body text, and content hash."""

    meta: PromptMeta
    body: str = Field(description="The raw prompt body (may contain $variable placeholders).")
    content_hash: str = Field(description="SHA-256 of the body for version tracking.")
    file_path: str | None = Field(
        default=None,
        description="Absolute path to the source file, if loaded from disk.",
    )

    def render(self, **variables: str) -> str:
        """Render the prompt body with variable substitution.

        Uses Python ``string.Template`` safe substitution so that
        unresolved ``$variables`` are left as-is rather than raising.

        Args:
            **variables: Key-value pairs to substitute into the body.

        Returns:
            Rendered prompt text.
        """
        return Template(self.body).safe_substitute(variables)


def _compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def load_prompt_file(path: Path) -> PromptTemplate:
    """Load a single prompt file from disk.

    Supports optional JSON front-matter delimited by ``---`` lines.
    If no front-matter is present, metadata is inferred from the filename.

    Args:
        path: Path to the ``.md`` file.

    Returns:
        A ``PromptTemplate`` with parsed metadata and body.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        json.JSONDecodeError: If front-matter is present but invalid JSON.
    """
    raw = path.read_text(encoding="utf-8")

    meta_dict: dict = {}
    body = raw

    match = _FRONT_MATTER_RE.match(raw)
    if match:
        try:
            meta_dict = json.loads(match.group(1))
        except json.JSONDecodeError:
            logger.warning("Invalid JSON front-matter in %s, using filename-based metadata", path)
        body = raw[match.end():]

    # Infer name from filename if not in front-matter
    if "name" not in meta_dict:
        meta_dict["name"] = path.stem

    body = body.strip()
    meta = PromptMeta(**meta_dict)

    return PromptTemplate(
        meta=meta,
        body=body,
        content_hash=_compute_hash(body),
        file_path=str(path.absolute()),
    )


def load_prompt_directory(directory: Path, *, glob_pattern: str = "*.md") -> list[PromptTemplate]:
    """Load all prompt files from a directory.

    Args:
        directory: Path to the directory containing ``.md`` files.
        glob_pattern: File glob pattern. Default ``*.md``.

    Returns:
        List of loaded ``PromptTemplate`` objects.

    Raises:
        FileNotFoundError: If the directory doesn't exist.
    """
    if not directory.is_dir():
        raise FileNotFoundError(f"Prompt directory not found: {directory}")

    templates: list[PromptTemplate] = []
    for path in sorted(directory.glob(glob_pattern)):
        if path.is_file():
            try:
                templates.append(load_prompt_file(path))
            except Exception as exc:
                logger.warning("Failed to load prompt %s: %s", path, exc)

    logger.debug("Loaded %d prompts from %s", len(templates), directory)
    return templates
