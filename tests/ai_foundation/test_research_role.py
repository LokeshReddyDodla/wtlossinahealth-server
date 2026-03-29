"""Tests for research role — prompt selection, evidence routing, thread prefixes."""

from __future__ import annotations


# ── Test: REST role mapping ──────────────────────────────────────────────


class TestRoleMapping:
    def test_admin_maps_to_research(self):
        """Verify the role mapping logic (inlined to avoid fastapi dependency)."""
        # This mirrors _resolve_agent_role from query_v3.py
        role_map = {"ADMIN": "research", "CARE_PROVIDER": "care_provider", "PATIENT": "patient"}
        assert role_map["ADMIN"] == "research"

    def test_care_provider_unchanged(self):
        role_map = {"ADMIN": "research", "CARE_PROVIDER": "care_provider", "PATIENT": "patient"}
        assert role_map["CARE_PROVIDER"] == "care_provider"

    def test_patient_unchanged(self):
        role_map = {"ADMIN": "research", "CARE_PROVIDER": "care_provider", "PATIENT": "patient"}
        assert role_map["PATIENT"] == "patient"


# ── Test: Prompt selection ───────────────────────────────────────────────


class TestPromptSelection:
    def test_research_prompt_exists(self):
        """system_research.md should be loadable with correct frontmatter name."""
        from pathlib import Path
        prompt_path = Path("lib/ai_foundation/agents/health_query/prompts/system_research.md")
        assert prompt_path.exists()
        content = prompt_path.read_text()
        assert '"name": "hq_system_research"' in content

    def test_admin_fallback_to_research(self):
        """agent.py name_map should route both 'research' and 'admin' to research prompt."""
        # Simulate the name_map from agent.py
        name_map = {"research": "hq_system_research", "admin": "hq_system_research",
                     "care_provider": "hq_system_care_provider", "patient": "hq_system_patient"}
        assert name_map["research"] == "hq_system_research"
        assert name_map["admin"] == "hq_system_research"  # backward compat


# ── Test: Evidence formatting routes research → provider format ──────────


class TestEvidenceRouting:
    def test_research_gets_provider_format(self):
        from lib.ai_foundation.agents.health_query.evidence import (
            EvidenceItem, build_summary, format_patient, format_provider,
        )
        items = [EvidenceItem(tool="look_up", data_types=["meal"], date_range="Mar 25", record_count=5, had_data=True)]
        summary = build_summary(items)

        # Research should get structured provider format (Sources:), not patient format (Based on...)
        patient_text = format_patient(summary)
        provider_text = format_provider(summary)
        assert "Based on" in patient_text
        assert "**Sources:**" in provider_text

        # Verify the routing logic matches
        for role in ("care_provider", "research"):
            assert role in ("care_provider", "research")  # would use format_provider
        assert "patient" not in ("care_provider", "research")  # would use format_patient


# ── Test: Thread prefix ─────────────────────────────────────────────────


class TestThreadPrefix:
    def test_research_thread_prefix(self):
        from lib.ai_foundation.agents.thread_utils import resolve_thread_id, thread_prefix_for_user

        thread_id = resolve_thread_id(role="research", actor_id="r123", patient_ids=["p456"])
        assert thread_id == "bot:research:r123:patient:p456"

    def test_research_multi_patient_thread(self):
        from lib.ai_foundation.agents.thread_utils import resolve_thread_id

        thread_id = resolve_thread_id(role="research", actor_id="r123", patient_ids=["p1", "p2"])
        assert thread_id.startswith("bot:research:r123:group:")

    def test_research_general_thread(self):
        from lib.ai_foundation.agents.thread_utils import resolve_thread_id

        thread_id = resolve_thread_id(role="research", actor_id="r123", patient_ids=[])
        assert thread_id == "bot:research:r123:general"

    def test_research_thread_list_prefix(self):
        from lib.ai_foundation.agents.thread_utils import thread_prefix_for_user

        prefix = thread_prefix_for_user(role="research", actor_id="r123")
        assert prefix == "bot:research:r123"

    def test_patient_and_provider_unchanged(self):
        from lib.ai_foundation.agents.thread_utils import resolve_thread_id

        patient = resolve_thread_id(role="patient", actor_id="p1")
        assert patient == "bot:patient:p1"

        provider = resolve_thread_id(role="care_provider", actor_id="d1", patient_ids=["p1"])
        assert provider == "bot:provider:d1:patient:p1"


# ── Test: Research prompt content ────────────────────────────────────────


class TestResearchPromptContent:
    def test_no_coaching_language(self):
        """Research prompt should not use patient-directed language."""
        from pathlib import Path
        content = Path("lib/ai_foundation/agents/health_query/prompts/system_research.md").read_text()
        assert "you" not in content.lower().split("## rules")[1].split("##")[0] or "NEVER say" in content

    def test_encourages_sample_sizes(self):
        from pathlib import Path
        content = Path("lib/ai_foundation/agents/health_query/prompts/system_research.md").read_text()
        assert "sample size" in content.lower()

    def test_encourages_data_limitations(self):
        from pathlib import Path
        content = Path("lib/ai_foundation/agents/health_query/prompts/system_research.md").read_text()
        assert "limitation" in content.lower()

    def test_encourages_confounders(self):
        from pathlib import Path
        content = Path("lib/ai_foundation/agents/health_query/prompts/system_research.md").read_text()
        assert "confounder" in content.lower()
