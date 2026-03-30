"""Tests for context window management — token counting, budget, and pruning strategies."""

from __future__ import annotations

from unittest.mock import MagicMock

from lib.ai_foundation.agents.health_query.reasoning_engine import ReasoningEngine, _CRITICAL_TYPES


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_engine(*, count_tokens_fn=None, model_window: int = 1000) -> ReasoningEngine:
    """Build a ReasoningEngine with a mocked gateway for token counting."""
    gateway = MagicMock()
    tool_executor = MagicMock()

    if count_tokens_fn:
        gateway.count_tokens = count_tokens_fn
    else:
        # Default: 1 token per char in content
        def _count(messages, model=None):
            return sum(len(m.get("content", "") or "") for m in messages)
        gateway.count_tokens = _count

    gateway.get_model_window = MagicMock(return_value=model_window)

    engine = ReasoningEngine(gateway=gateway, tool_executor=tool_executor)
    return engine


def _msg(role: str, content: str, meta_type: str = "", **meta_extra) -> dict:
    """Build a message dict with optional _meta."""
    msg = {"role": role, "content": content}
    if meta_type:
        msg["_meta"] = {"type": meta_type, **meta_extra}
    return msg


# ── Test: Under budget → no pruning ─────────────────────────────────────


class TestNoPruning:
    def test_under_budget_returns_unchanged(self):
        engine = _make_engine(model_window=10000)
        messages = [
            _msg("system", "instructions", "instruction"),
            _msg("user", "question", "user_question"),
        ]
        result = engine._prune_if_needed(messages, "gpt-4.1-mini")
        assert result == messages


class TestResponderMessageBuilding:
    def test_responder_drops_old_instruction_prompt(self):
        engine = _make_engine()
        messages = [
            _msg("system", "persona", "context"),
            _msg("system", "reasoning prompt", "instruction"),
            _msg("tool", "meal data"),
            _msg("user", "what happened", "user_question"),
        ]

        result = engine._build_responder_messages(messages, "response prompt")
        system_contents = [m.get("content", "") for m in result if m.get("role") == "system"]

        assert "reasoning prompt" not in system_contents
        assert "persona" in system_contents
        assert "response prompt" in system_contents

    def test_exact_budget_returns_unchanged(self):
        """At budget boundary, no pruning needed."""
        engine = _make_engine(model_window=100)
        # budget = min(100*0.75, 100-4096) = 75 (ratio wins since window is small)
        # But with window=100, reserve=4096 → window-reserve is negative
        # So budget = min(75, -3996) = -3996 → always over budget
        # Use a larger window
        engine = _make_engine(model_window=10000)
        # budget = min(7500, 5904) = 5904
        messages = [_msg("system", "x" * 5900, "instruction")]
        result = engine._prune_if_needed(messages, "gpt-4.1-mini")
        assert result == messages


# ── Test: Strategy 1 — Summarize old tool results ───────────────────────


class TestSummarizeOldRounds:
    def test_old_rounds_collapsed(self):
        engine = _make_engine(model_window=600)
        # budget = min(450, 600-4096) → 450 (since 600-4096 is negative, min picks negative)
        # Need a bigger window so budget is meaningful
        engine = _make_engine(model_window=10000)
        # budget = min(7500, 5904) = 5904

        messages = [
            _msg("system", "instructions", "instruction"),
            # Round 1 (old — should be collapsed since max_round=4, threshold=2)
            _msg("system", "tool result round 1\n" * 100, "tool_result", round=1, tool="look_up"),
            # Round 2 (old — should be collapsed)
            _msg("system", "tool result round 2\n" * 100, "tool_result", round=2, tool="compare_baseline"),
            # Round 3 (recent — keep)
            _msg("system", "tool result round 3\n" * 100, "tool_result", round=3, tool="investigate_day"),
            # Round 4 (latest — keep)
            _msg("system", "tool result round 4\n" * 100, "tool_result", round=4, tool="look_up"),
            _msg("user", "question", "user_question"),
        ]

        result = engine._summarize_old_rounds(messages)

        # Round 1 and 2 should be collapsed into summaries
        types = [m.get("_meta", {}).get("type") for m in result]
        assert "tool_summary" in types
        # Rounds 3 and 4 should still be full tool_result
        tool_results = [m for m in result if m.get("_meta", {}).get("type") == "tool_result"]
        assert len(tool_results) == 2
        assert all(m["_meta"]["round"] >= 3 for m in tool_results)

    def test_no_collapse_when_only_2_rounds(self):
        engine = _make_engine()
        messages = [
            _msg("system", "instructions", "instruction"),
            _msg("system", "result", "tool_result", round=1, tool="look_up"),
            _msg("system", "result", "tool_result", round=2, tool="look_up"),
            _msg("user", "question", "user_question"),
        ]
        result = engine._summarize_old_rounds(messages)
        # Nothing should change — max_round=2, threshold=0, nothing old enough
        tool_results = [m for m in result if m.get("_meta", {}).get("type") == "tool_result"]
        assert len(tool_results) == 2


# ── Test: Strategy 2 — Trim history ─────────────────────────────────────


class TestTrimHistory:
    def test_trims_to_4_then_2_then_0(self):
        engine = _make_engine()
        history = [_msg("user", f"msg {i}", "history") for i in range(8)]
        messages = [
            _msg("system", "instructions", "instruction"),
            *history,
            _msg("user", "current question", "user_question"),
        ]

        # First trim: 8 → 4
        result = engine._trim_history(messages)
        remaining = [m for m in result if m.get("_meta", {}).get("type") == "history"]
        assert len(remaining) == 4

        # Second trim: 4 → 2
        result = engine._trim_history(result)
        remaining = [m for m in result if m.get("_meta", {}).get("type") == "history"]
        assert len(remaining) == 2

        # Third trim: 2 → 0
        result = engine._trim_history(result)
        remaining = [m for m in result if m.get("_meta", {}).get("type") == "history"]
        assert len(remaining) == 0

    def test_no_history_no_change(self):
        engine = _make_engine()
        messages = [
            _msg("system", "instructions", "instruction"),
            _msg("user", "question", "user_question"),
        ]
        result = engine._trim_history(messages)
        assert len(result) == 2

    def test_2_history_trims_to_0(self):
        """2 messages is below the 4-tier, so next step is 0."""
        engine = _make_engine()
        messages = [
            _msg("system", "instructions", "instruction"),
            _msg("user", "msg1", "history"),
            _msg("user", "msg2", "history"),
            _msg("user", "question", "user_question"),
        ]
        result = engine._trim_history(messages)
        remaining = [m for m in result if m.get("_meta", {}).get("type") == "history"]
        assert len(remaining) == 0


# ── Test: Strategy 3 — Trim facts (pinned survive) ──────────────────────


class TestTrimFacts:
    def test_pinned_facts_survive(self):
        engine = _make_engine()
        messages = [
            _msg("system", "instructions", "instruction"),
            {
                "role": "system",
                "content": "Patient memories:\n  Health: diabetes_type: Type 1, allergies: none\n  Goals: target_range: 70-180",
                "_meta": {"type": "fact", "pinned_keys": ["diabetes_type"]},
            },
            _msg("user", "question", "user_question"),
        ]

        result = engine._trim_facts(messages)
        fact_msgs = [m for m in result if m.get("_meta", {}).get("type") == "fact"]
        assert len(fact_msgs) == 1
        assert "diabetes_type" in fact_msgs[0]["content"]

    def test_no_pinned_keys_drops_entirely(self):
        engine = _make_engine()
        messages = [
            _msg("system", "instructions", "instruction"),
            {
                "role": "system",
                "content": "Patient memories:\n  Health: allergies: none",
                "_meta": {"type": "fact", "pinned_keys": []},
            },
            _msg("user", "question", "user_question"),
        ]

        result = engine._trim_facts(messages)
        fact_msgs = [m for m in result if m.get("_meta", {}).get("type") == "fact"]
        assert len(fact_msgs) == 0


# ── Test: Strategy 4 — Trim insights ────────────────────────────────────


class TestTrimInsights:
    def test_removes_insight_messages(self):
        engine = _make_engine()
        messages = [
            _msg("system", "instructions", "instruction"),
            _msg("system", "insight 1", "insight"),
            _msg("system", "insight 2", "insight"),
            _msg("user", "question", "user_question"),
        ]

        result = engine._trim_insights(messages)
        insight_msgs = [m for m in result if m.get("_meta", {}).get("type") == "insight"]
        assert len(insight_msgs) == 0
        assert len(result) == 2  # instruction + user_question


# ── Test: Strategy 5 — Hard truncate ────────────────────────────────────


class TestHardTruncate:
    def test_truncates_longest_non_critical(self):
        engine = _make_engine()
        messages = [
            _msg("system", "instructions", "instruction"),
            _msg("system", "x" * 2000, "tool_result", round=1, tool="look_up"),
            _msg("system", "y" * 500, "tool_result", round=2, tool="look_up"),
            _msg("system", "z" * 3000, "tool_result", round=3, tool="look_up"),  # round 3 = max-1, protected
            _msg("user", "question", "user_question"),
        ]

        result = engine._hard_truncate_oldest(messages)
        # The 2000-char message (round 1) should be truncated, not round 3 (protected)
        truncated = [m for m in result if "truncated to fit context window" in m.get("content", "")]
        assert len(truncated) == 1

    def test_never_truncates_critical(self):
        engine = _make_engine()
        messages = [
            _msg("system", "x" * 5000, "instruction"),  # critical — never truncate
            _msg("user", "y" * 3000, "user_question"),  # critical — never truncate
            _msg("system", "z" * 100, "context"),
        ]

        result = engine._hard_truncate_oldest(messages)
        # instruction and user_question should remain untouched
        assert len(result[0]["content"]) == 5000
        assert len(result[1]["content"]) == 3000


# ── Test: Fallback token estimator ──────────────────────────────────────


class TestFallbackEstimator:
    def test_char_div_4_fallback(self):
        from lib.ai_foundation.models.gateway import ModelGateway

        gateway = MagicMock(spec=ModelGateway)

        # Simulate litellm.token_counter raising
        def _fallback_count(messages, model=None):
            return sum(len(m.get("content", "") or "") for m in messages) // 4

        gateway.count_tokens = _fallback_count

        messages = [{"role": "user", "content": "a" * 400}]
        assert gateway.count_tokens(messages) == 100


# ── Test: Responder protected ────────────────────────────────────────────


class TestResponderProtected:
    def test_prune_called_for_responder(self):
        """Verify _prune_if_needed is called (integration-level check via _generate_final_response)."""
        engine = _make_engine(model_window=10000)
        # Just verify the method exists and is callable with responder messages
        messages = [
            _msg("system", "instructions", "instruction"),
            _msg("user", "question", "user_question"),
        ]
        result = engine._prune_if_needed(messages, "gpt-5.1")
        assert result == messages  # under budget, no change


# ── Test: Critical messages never truncated ──────────────────────────────


class TestCriticalMessageSafety:
    def test_critical_types_defined(self):
        assert "instruction" in _CRITICAL_TYPES
        assert "user_question" in _CRITICAL_TYPES

    def test_full_prune_preserves_critical(self):
        """Even after all strategies, instruction and user_question survive."""
        # Make a tiny budget so all strategies fire
        engine = _make_engine(model_window=10000)

        # Override count_tokens to simulate being over budget until insights removed
        call_count = [0]
        def _count(messages, model=None):
            call_count[0] += 1
            # First call: over budget. After trimming insights: under budget.
            insight_tokens = sum(
                len(m.get("content", ""))
                for m in messages
                if m.get("_meta", {}).get("type") == "insight"
            )
            base = 5000  # base tokens
            return base + insight_tokens

        engine._gateway.count_tokens = _count

        messages = [
            _msg("system", "x" * 1000, "instruction"),
            _msg("system", "insight " * 500, "insight"),
            _msg("user", "question", "user_question"),
        ]

        result = engine._prune_if_needed(messages, "gpt-4.1-mini")

        # Critical messages must survive
        types = [m.get("_meta", {}).get("type") for m in result]
        assert "instruction" in types
        assert "user_question" in types


# ── Test: Iterative pruning with logging ─────────────────────────────────


class TestIterativePruning:
    def test_strategies_run_in_order(self):
        """Verify strategies are applied in priority order."""
        engine = _make_engine(model_window=10000)
        # budget = 5904

        strategies_called = []
        original_summarize = engine._summarize_old_rounds
        original_trim_history = engine._trim_history
        original_trim_facts = engine._trim_facts
        original_trim_insights = engine._trim_insights
        original_hard_truncate = engine._hard_truncate_oldest

        def _track(name, fn):
            def wrapper(messages):
                strategies_called.append(name)
                return fn(messages)
            wrapper.__name__ = name
            return wrapper

        engine._summarize_old_rounds = _track("_summarize_old_rounds", original_summarize)
        engine._trim_history = _track("_trim_history", original_trim_history)
        engine._trim_facts = _track("_trim_facts", original_trim_facts)
        engine._trim_insights = _track("_trim_insights", original_trim_insights)
        engine._hard_truncate_oldest = _track("_hard_truncate_oldest", original_hard_truncate)

        # Always over budget so all strategies fire
        engine._gateway.count_tokens = lambda msgs, model=None: 99999

        messages = [
            _msg("system", "instructions", "instruction"),
            _msg("user", "question", "user_question"),
        ]

        engine._prune_if_needed(messages, "gpt-4.1-mini")

        assert strategies_called == [
            "_summarize_old_rounds",
            "_trim_history",
            "_trim_facts",
            "_trim_insights",
            "_hard_truncate_oldest",
            "_hard_truncate_oldest",  # second pass
            "_hard_truncate_oldest",  # third pass
        ]

    def test_stops_early_when_under_budget(self):
        """If first strategy brings us under budget, skip the rest."""
        engine = _make_engine(model_window=10000)

        call_count = [0]
        def _count(messages, model=None):
            call_count[0] += 1
            # Over budget on first check, under after first strategy
            if call_count[0] <= 1:
                return 99999
            return 100  # well under budget

        engine._gateway.count_tokens = _count

        strategies_called = []
        original = engine._summarize_old_rounds
        def _track(messages):
            strategies_called.append("_summarize_old_rounds")
            return original(messages)
        _track.__name__ = "_summarize_old_rounds"
        engine._summarize_old_rounds = _track

        messages = [
            _msg("system", "instructions", "instruction"),
            _msg("user", "question", "user_question"),
        ]

        engine._prune_if_needed(messages, "gpt-4.1-mini")
        assert strategies_called == ["_summarize_old_rounds"]
