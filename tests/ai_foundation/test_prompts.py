"""Tests for Prompt Management — loader and registry."""

import json
import tempfile
from pathlib import Path

import pytest

from lib.ai_foundation.prompts.loader import (
    PromptMeta,
    PromptTemplate,
    load_prompt_directory,
    load_prompt_file,
)
from lib.ai_foundation.prompts.registry import PromptNotFoundError, PromptRegistry


class TestPromptLoader:
    def test_load_plain_markdown(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("You are a helpful assistant.")
        t = load_prompt_file(f)
        assert t.meta.name == "test"
        assert t.body == "You are a helpful assistant."
        assert t.content_hash
        assert t.file_path

    def test_load_with_front_matter(self, tmp_path):
        f = tmp_path / "system_patient.md"
        f.write_text(
            '---\n{"name": "sys_patient", "version": "2.0", "domain": "cgm", "task": "system"}\n---\n\nHello patient.'
        )
        t = load_prompt_file(f)
        assert t.meta.name == "sys_patient"
        assert t.meta.version == "2.0"
        assert t.meta.domain == "cgm"
        assert t.meta.task == "system"
        assert t.body == "Hello patient."

    def test_load_with_invalid_front_matter_falls_back(self, tmp_path):
        f = tmp_path / "bad.md"
        f.write_text("---\nnot json\n---\n\nContent here.")
        t = load_prompt_file(f)
        assert t.meta.name == "bad"
        assert t.body == "Content here."

    def test_load_directory(self, tmp_path):
        (tmp_path / "a.md").write_text("Prompt A")
        (tmp_path / "b.md").write_text("Prompt B")
        (tmp_path / "not_md.txt").write_text("Not loaded")
        templates = load_prompt_directory(tmp_path)
        assert len(templates) == 2
        names = {t.meta.name for t in templates}
        assert names == {"a", "b"}

    def test_load_nonexistent_directory_raises(self):
        with pytest.raises(FileNotFoundError):
            load_prompt_directory(Path("/nonexistent"))

    def test_render(self, tmp_path):
        f = tmp_path / "greet.md"
        f.write_text("Hello $name, your goal is $goal.")
        t = load_prompt_file(f)
        rendered = t.render(name="John", goal="fat loss")
        assert rendered == "Hello John, your goal is fat loss."

    def test_render_safe_substitute(self, tmp_path):
        f = tmp_path / "partial.md"
        f.write_text("Hello $name, time is $time.")
        t = load_prompt_file(f)
        rendered = t.render(name="Jane")
        assert "Jane" in rendered
        assert "$time" in rendered  # unresolved var kept

    def test_content_hash_changes_with_content(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("Version 1")
        t1 = load_prompt_file(f)
        f.write_text("Version 2")
        t2 = load_prompt_file(f)
        assert t1.content_hash != t2.content_hash

    def test_load_existing_health_query_prompts(self):
        prompts_dir = Path("lib/services/health_query_agent/prompts")
        if prompts_dir.exists():
            templates = load_prompt_directory(prompts_dir)
            assert len(templates) >= 1
            for t in templates:
                assert t.meta.name
                assert t.body


class TestPromptRegistry:
    def test_register_and_get(self, prompt_registry):
        t = PromptTemplate(
            meta=PromptMeta(name="test"), body="content", content_hash="abc",
        )
        prompt_registry.register(t, namespace="test_ns")
        result = prompt_registry.get("test")
        assert result.body == "content"

    def test_get_not_found_raises(self, prompt_registry):
        with pytest.raises(PromptNotFoundError):
            prompt_registry.get("nonexistent")

    def test_version_mismatch_raises(self, prompt_registry):
        t = PromptTemplate(
            meta=PromptMeta(name="versioned", version="1.0.0"),
            body="v1", content_hash="abc",
        )
        prompt_registry.register(t)
        with pytest.raises(PromptNotFoundError, match="version mismatch"):
            prompt_registry.get("versioned", version="2.0.0")

    def test_select_by_domain(self, prompt_registry):
        prompt_registry.register(PromptTemplate(
            meta=PromptMeta(name="cgm_sys", domain="cgm", task="system"),
            body="CGM", content_hash="a",
        ))
        prompt_registry.register(PromptTemplate(
            meta=PromptMeta(name="meal_sys", domain="meal", task="system"),
            body="Meal", content_hash="b",
        ))
        results = prompt_registry.select(domain="cgm")
        assert len(results) == 1
        assert results[0].meta.name == "cgm_sys"

    def test_select_by_task(self, prompt_registry):
        prompt_registry.register(PromptTemplate(
            meta=PromptMeta(name="p1", task="playbook"), body="pb", content_hash="a",
        ))
        prompt_registry.register(PromptTemplate(
            meta=PromptMeta(name="p2", task="system"), body="sys", content_hash="b",
        ))
        results = prompt_registry.select(task="playbook")
        assert len(results) == 1

    def test_select_by_role(self, prompt_registry):
        prompt_registry.register(PromptTemplate(
            meta=PromptMeta(name="patient", role="patient"), body="p", content_hash="a",
        ))
        prompt_registry.register(PromptTemplate(
            meta=PromptMeta(name="provider", role="care_provider"), body="cp", content_hash="b",
        ))
        results = prompt_registry.select(role="care_provider")
        assert len(results) == 1
        assert results[0].meta.name == "provider"

    def test_register_directory(self, prompt_registry, tmp_path):
        (tmp_path / "a.md").write_text("Prompt A")
        (tmp_path / "b.md").write_text("Prompt B")
        count = prompt_registry.register_directory(tmp_path, namespace="test")
        assert count == 2
        assert len(prompt_registry) == 2
        assert "test" in prompt_registry.list_namespaces()

    def test_select_by_namespace(self, prompt_registry, tmp_path):
        d1 = tmp_path / "d1"
        d2 = tmp_path / "d2"
        d1.mkdir()
        d2.mkdir()
        (d1 / "a.md").write_text("A")
        (d2 / "b.md").write_text("B")
        prompt_registry.register_directory(d1, namespace="ns1")
        prompt_registry.register_directory(d2, namespace="ns2")
        ns1 = prompt_registry.select(namespace="ns1")
        assert len(ns1) == 1
        assert ns1[0].meta.name == "a"

    def test_contains(self, prompt_registry):
        prompt_registry.register(PromptTemplate(
            meta=PromptMeta(name="exists"), body="x", content_hash="a",
        ))
        assert "exists" in prompt_registry
        assert "nope" not in prompt_registry

    def test_repr(self, prompt_registry):
        assert "PromptRegistry" in repr(prompt_registry)
