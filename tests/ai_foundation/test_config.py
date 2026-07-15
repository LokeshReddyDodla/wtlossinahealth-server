"""Tests for AIFoundationSettings — env prefixing and alias behavior.

Locks the two conventions everything else relies on:
- Regular fields read AI_-prefixed env vars (case-insensitive)
- Langfuse fields use validation_alias to read bare LANGFUSE_* vars,
  shared with LiteLLM's native callback config
"""

from __future__ import annotations

from lib.ai_foundation.config import AIFoundationSettings


class TestEnvPrefix:
    def test_ai_prefix_overrides_default(self, monkeypatch):
        monkeypatch.setenv("AI_REASONING_DEFAULT_TIER", "advanced")
        s = AIFoundationSettings()
        assert s.REASONING_DEFAULT_TIER == "advanced"

    def test_prefix_is_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("ai_max_context_facts", "25")
        s = AIFoundationSettings()
        assert s.MAX_CONTEXT_FACTS == 25

    def test_unprefixed_var_is_ignored(self, monkeypatch):
        monkeypatch.setenv("MAX_CONTEXT_FACTS", "99")
        s = AIFoundationSettings()
        assert s.MAX_CONTEXT_FACTS != 99

    def test_int_coercion(self, monkeypatch):
        monkeypatch.setenv("AI_QDRANT_RESULT_LIMIT", "77")
        s = AIFoundationSettings()
        assert s.QDRANT_RESULT_LIMIT == 77
        assert isinstance(s.QDRANT_RESULT_LIMIT, int)


class TestLangfuseAliases:
    def test_langfuse_reads_bare_env_var(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test-123")
        s = AIFoundationSettings()
        assert s.LANGFUSE_PUBLIC_KEY == "pk-test-123"

    def test_langfuse_enabled_flag(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_ENABLED", "false")
        s = AIFoundationSettings()
        assert s.LANGFUSE_ENABLED is False


class TestModelDefaults:
    def test_reasoning_models_configured(self):
        """The three routing models must always be non-empty — the registry
        builds task routes from them at startup."""
        s = AIFoundationSettings()
        assert s.REASONING_THINKER_MODEL
        assert s.REASONING_RESPONDER_MODEL
        assert s.REASONING_ADVANCED_THINKER_MODEL

    def test_context_budget_ratio_sane(self):
        s = AIFoundationSettings()
        assert 0.0 < s.CONTEXT_BUDGET_RATIO <= 1.0
