"""Tests for ModelRegistry — model registration, routing, and fallback chains."""

import pytest

from lib.ai_foundation.models.registry import (
    ModelGatewayError,
    ModelNotFoundError,
    ModelProvider,
    ModelRegistry,
    ModelSpec,
    ModelTask,
    NoRouteError,
    TaskRoute,
    build_default_registry,
)


class TestModelSpec:
    def test_create_with_defaults(self):
        spec = ModelSpec(model_id="gpt-4.1-mini")
        assert spec.provider == ModelProvider.OPENAI
        assert spec.temperature == 0.0
        assert spec.supports_structured is True
        assert spec.supports_streaming is True

    def test_with_overrides(self):
        spec = ModelSpec(model_id="gpt-4.1-mini", temperature=0.0)
        overridden = spec.with_overrides(temperature=0.7, max_tokens=500)
        assert overridden.temperature == 0.7
        assert overridden.max_tokens == 500
        assert overridden.model_id == "gpt-4.1-mini"
        # Original unchanged
        assert spec.temperature == 0.0
        assert spec.max_tokens is None


class TestModelRegistry:
    def test_register_and_get(self):
        reg = ModelRegistry()
        spec = ModelSpec(model_id="test-model", provider=ModelProvider.OPENAI)
        reg.register(spec)
        result = reg.get("test-model")
        assert result.model_id == "test-model"

    def test_get_returns_copy(self):
        reg = ModelRegistry()
        reg.register(ModelSpec(model_id="m1"))
        a = reg.get("m1")
        b = reg.get("m1")
        assert a == b
        assert a is not b

    def test_get_unknown_raises(self):
        reg = ModelRegistry()
        with pytest.raises(ModelNotFoundError, match="not registered"):
            reg.get("nonexistent")

    def test_register_many(self):
        reg = ModelRegistry()
        reg.register_many([
            ModelSpec(model_id="a"),
            ModelSpec(model_id="b"),
            ModelSpec(model_id="c"),
        ])
        assert len(reg.list_models()) == 3

    def test_contains(self):
        reg = ModelRegistry()
        reg.register(ModelSpec(model_id="m1"))
        assert "m1" in reg
        assert "m2" not in reg

    def test_set_task_route(self):
        reg = ModelRegistry()
        reg.register(ModelSpec(model_id="m1"))
        reg.register(ModelSpec(model_id="m2"))
        reg.set_task_route(ModelTask.INTENT_EXTRACTION, primary="m1", fallbacks=["m2"])
        spec = reg.route(ModelTask.INTENT_EXTRACTION)
        assert spec.model_id == "m1"

    def test_set_task_route_unregistered_model_raises(self):
        reg = ModelRegistry()
        with pytest.raises(ModelNotFoundError, match="unregistered model"):
            reg.set_task_route(ModelTask.INTENT_EXTRACTION, primary="ghost")

    def test_route_no_route_raises(self):
        reg = ModelRegistry()
        with pytest.raises(NoRouteError, match="No route configured"):
            reg.route(ModelTask.INTENT_EXTRACTION)

    def test_get_fallback_chain(self):
        reg = ModelRegistry()
        reg.register_many([
            ModelSpec(model_id="primary"),
            ModelSpec(model_id="fallback1"),
            ModelSpec(model_id="fallback2"),
        ])
        reg.set_task_route(
            ModelTask.RESPONSE_GENERATION,
            primary="primary",
            fallbacks=["fallback1", "fallback2"],
        )
        chain = reg.get_fallback_chain(ModelTask.RESPONSE_GENERATION)
        assert [s.model_id for s in chain] == ["primary", "fallback1", "fallback2"]

    def test_list_models_by_tag(self):
        reg = ModelRegistry()
        reg.register(ModelSpec(model_id="fast", tags=["fast", "cheap"]))
        reg.register(ModelSpec(model_id="slow", tags=["powerful"]))
        fast = reg.list_models(tags=["fast"])
        assert len(fast) == 1
        assert fast[0].model_id == "fast"

    def test_list_tasks(self):
        reg = ModelRegistry()
        reg.register(ModelSpec(model_id="m1"))
        reg.set_task_route(ModelTask.CLASSIFICATION, primary="m1")
        tasks = reg.list_tasks()
        assert ModelTask.CLASSIFICATION in tasks

    def test_overwrite_existing_model(self):
        reg = ModelRegistry()
        reg.register(ModelSpec(model_id="m1", temperature=0.0))
        reg.register(ModelSpec(model_id="m1", temperature=0.9))
        assert reg.get("m1").temperature == 0.9


class TestDefaultRegistry:
    def test_has_expected_models(self, registry):
        assert "gpt-4.1-mini" in registry
        assert "gpt-5.1" in registry
        assert "text-embedding-3-large" in registry

    def test_all_tasks_routed(self, registry):
        for task in ModelTask:
            spec = registry.route(task)
            assert spec.model_id

    def test_intent_extraction_route(self, registry):
        spec = registry.route(ModelTask.INTENT_EXTRACTION)
        assert spec.model_id == "gpt-4.1-mini"

    def test_response_generation_route(self, registry):
        spec = registry.route(ModelTask.RESPONSE_GENERATION)
        assert spec.model_id == "gpt-5.1"

    def test_fallback_chains_exist(self, registry):
        chain = registry.get_fallback_chain(ModelTask.RESPONSE_GENERATION)
        assert len(chain) >= 2

    def test_repr(self, registry):
        r = repr(registry)
        assert "ModelRegistry" in r
        assert "gpt-4.1-mini" in r
