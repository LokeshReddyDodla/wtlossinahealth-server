"""
Prompt Registry — central index for all prompt templates across the platform.

Agents register their prompt directories at startup. The registry makes
prompts discoverable by name, domain, task, or role — enabling prompt
reuse across agents and version tracking for evaluation.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .loader import PromptTemplate, load_prompt_directory

logger = logging.getLogger(__name__)


class PromptNotFoundError(Exception):
    """Raised when a requested prompt is not in the registry."""


class PromptRegistry:
    """Global prompt registry that agents register their prompts into.

    Thread-safe for reads after initial configuration.

    Example::

        registry = PromptRegistry()

        # Register entire directories
        registry.register_directory(
            Path("lib/services/health_query_agent/prompts"),
            namespace="health_query",
        )
        registry.register_directory(
            Path("lib/services/health_query_agent/v2/playbooks"),
            namespace="health_query.playbooks",
        )

        # Look up by name
        prompt = registry.get("system_patient")

        # Search by criteria
        playbooks = registry.select(domain="cgm", task="playbook")
    """

    def __init__(self) -> None:
        self._prompts: dict[str, PromptTemplate] = {}
        self._namespaces: dict[str, list[str]] = {}

    # -- Registration -------------------------------------------------------

    def register(self, template: PromptTemplate, namespace: str = "default") -> None:
        """Register a single prompt template.

        If a prompt with the same name already exists, it is overwritten
        with a warning.
        """
        key = template.meta.name
        if key in self._prompts:
            logger.debug(
                "Overwriting prompt %r (hash %s → %s)",
                key,
                self._prompts[key].content_hash,
                template.content_hash,
            )
        self._prompts[key] = template

        ns_list = self._namespaces.setdefault(namespace, [])
        if key not in ns_list:
            ns_list.append(key)

    def register_directory(
        self,
        directory: Path,
        namespace: str = "default",
        *,
        glob_pattern: str = "*.md",
    ) -> int:
        """Bulk-register all ``.md`` files from a directory.

        Args:
            directory: Path to the prompt directory.
            namespace: Logical grouping (e.g. ``"health_query"``).
            glob_pattern: File glob pattern.

        Returns:
            Number of prompts registered.
        """
        templates = load_prompt_directory(directory, glob_pattern=glob_pattern)
        for t in templates:
            self.register(t, namespace=namespace)
        logger.debug(
            "Registered %d prompts from %s under namespace %r",
            len(templates),
            directory,
            namespace,
        )
        return len(templates)

    # -- Lookup -------------------------------------------------------------

    def get(self, name: str, *, version: str | None = None) -> PromptTemplate:
        """Retrieve a prompt by exact name.

        Args:
            name: The prompt name (e.g. ``"system_patient"``).
            version: Optional version filter. If provided and the registered
                prompt's version doesn't match, raises ``PromptNotFoundError``.

        Raises:
            PromptNotFoundError: If the prompt doesn't exist or version mismatches.
        """
        template = self._prompts.get(name)
        if template is None:
            raise PromptNotFoundError(
                f"Prompt {name!r} not found. Available: {sorted(self._prompts.keys())}"
            )
        if version and template.meta.version != version:
            raise PromptNotFoundError(
                f"Prompt {name!r} version mismatch: wanted {version!r}, "
                f"have {template.meta.version!r}"
            )
        return template

    def select(
        self,
        *,
        domain: str | None = None,
        task: str | None = None,
        role: str | None = None,
        tags: list[str] | None = None,
        namespace: str | None = None,
    ) -> list[PromptTemplate]:
        """Search prompts by criteria. All filters are AND-combined.

        Args:
            domain: Filter by health domain (e.g. ``"cgm"``, ``"meal"``).
            task: Filter by task type (e.g. ``"playbook"``, ``"system"``).
            role: Filter by target role (e.g. ``"patient"``).
            tags: Filter by tags (all must match).
            namespace: Restrict to prompts registered under this namespace.

        Returns:
            List of matching ``PromptTemplate`` objects.
        """
        candidates: list[PromptTemplate]

        if namespace:
            names = self._namespaces.get(namespace, [])
            candidates = [self._prompts[n] for n in names if n in self._prompts]
        else:
            candidates = list(self._prompts.values())

        results: list[PromptTemplate] = []
        for t in candidates:
            if domain and t.meta.domain != domain:
                continue
            if task and t.meta.task != task:
                continue
            if role and t.meta.role != role:
                continue
            if tags and not set(tags).issubset(set(t.meta.tags)):
                continue
            results.append(t)

        return results

    # -- Utilities ----------------------------------------------------------

    def list_names(self, namespace: str | None = None) -> list[str]:
        """Return all registered prompt names, optionally filtered by namespace."""
        if namespace:
            return list(self._namespaces.get(namespace, []))
        return sorted(self._prompts.keys())

    def list_namespaces(self) -> list[str]:
        """Return all registered namespace names."""
        return sorted(self._namespaces.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._prompts

    def __len__(self) -> int:
        return len(self._prompts)

    def __repr__(self) -> str:
        return (
            f"PromptRegistry(prompts={len(self._prompts)}, "
            f"namespaces={sorted(self._namespaces.keys())})"
        )
