"""
Context Pruner — manages message lists to fit within LLM context windows.

Applies 5 strategies in priority order, stopping as soon as the token
budget is met. Designed to be model-agnostic and reusable across agents.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from lib.ai_foundation.config import settings

if TYPE_CHECKING:
    from lib.ai_foundation.models.gateway import ModelGateway

logger = logging.getLogger(__name__)

# Meta types that must NEVER be pruned (system instructions + current question)
CRITICAL_TYPES = frozenset({"system_prompt", "instruction", "user_question", "evidence_summary"})

# Floor for _hard_truncate_oldest — never truncate below this many characters
MIN_TRUNCATION_CHARS = 500


class ContextPruner:
    """Prunes LLM message lists to fit within context window budgets.

    Uses 5 strategies in priority order:
        1. Summarize old tool rounds (deterministic collapse)
        2. Trim conversation history
        3. Trim facts to pinned-only
        4. Remove insight messages
        5. Hard truncate longest non-critical message
    """

    def __init__(self, *, gateway: ModelGateway) -> None:
        self._gateway = gateway

    def get_input_budget(self, model: str) -> int:
        """Calculate the max input tokens for a model."""
        window = self._gateway.get_model_window(model)
        return max(1, min(
            int(window * settings.CONTEXT_BUDGET_RATIO),
            window - settings.CONTEXT_RESPONSE_RESERVE,
        ))

    def prune_if_needed(self, messages: list[dict[str, Any]], model: str) -> list[dict[str, Any]]:
        """Prune messages to fit within the model's context window.

        Applies 5 strategies in priority order, stopping as soon as under budget.
        """
        budget = self.get_input_budget(model)
        tokens = self._gateway.count_tokens(messages, model)

        if tokens <= budget:
            logger.debug("Token budget OK: %d/%d (%.0f%%)", tokens, budget, tokens / max(budget, 1) * 100)
            return messages

        logger.info("Token budget exceeded: %d/%d — pruning", tokens, budget)

        for strategy in [
            self._summarize_old_rounds,
            self._trim_history,
            self._trim_facts,
            self._trim_insights,
            self._hard_truncate_oldest,
            self._hard_truncate_oldest,  # second pass for severely over-budget contexts
            self._hard_truncate_oldest,  # third pass
        ]:
            messages = strategy(messages)
            tokens = self._gateway.count_tokens(messages, model)
            logger.info("After %s: %d tokens (%.0f%%)", strategy.__name__, tokens, tokens / max(budget, 1) * 100)
            if tokens <= budget:
                return messages

        logger.warning("All pruning strategies exhausted — still at %d/%d tokens", tokens, budget)
        return messages  # best effort

    def _summarize_old_rounds(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Strategy 1: Collapse tool results from rounds > 2 ago into deterministic summaries."""
        max_round = 0
        for msg in messages:
            meta = msg.get("_meta", {})
            r = meta.get("round", 0)
            if r > max_round:
                max_round = r

        if max_round <= 2:
            return messages

        threshold = max_round - 2
        result: list[dict[str, Any]] = []
        pending_round: int = 0
        pending_summaries: list[str] = []

        for msg in messages:
            meta = msg.get("_meta", {})
            msg_type = meta.get("type", "")
            msg_round = meta.get("round", 0)

            if msg_type == "tool_result" and msg_round > 0 and msg_round <= threshold:
                if msg_round != pending_round and pending_summaries:
                    result.append({
                        "role": "system",
                        "content": "\n".join(pending_summaries),
                        "_meta": {"type": "tool_summary", "round": pending_round},
                    })
                    pending_summaries = []
                pending_round = msg_round
                tool_name = meta.get("tool", "tool")
                content = msg.get("content", "")
                has_no_data = content.startswith("[NO_DATA]")
                status = "no data" if has_no_data else f"{len(content)} chars"
                pending_summaries.append(f"  {tool_name} → {status}")
            elif msg_type == "tool_summary":
                result.append(msg)
            else:
                if pending_summaries:
                    result.append({
                        "role": "system",
                        "content": f"[Round {pending_round} summary]\n" + "\n".join(pending_summaries),
                        "_meta": {"type": "tool_summary", "round": pending_round},
                    })
                    pending_summaries = []
                if msg.get("role") == "assistant" and msg.get("tool_calls") and meta.get("round", 0) <= threshold and meta.get("round", 0) > 0:
                    continue
                if msg.get("role") == "tool" and meta.get("round", 0) <= threshold and meta.get("round", 0) > 0:
                    continue
                result.append(msg)

        if pending_summaries:
            result.append({
                "role": "system",
                "content": f"[Round {pending_round} summary]\n" + "\n".join(pending_summaries),
                "_meta": {"type": "tool_summary", "round": pending_round},
            })

        return result

    def _trim_history(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Strategy 2: Reduce conversation history messages progressively.

        Each call trims to the next lower tier: >4→4, >2→2, >0→0.
        """
        history_msgs = [(i, m) for i, m in enumerate(messages) if m.get("_meta", {}).get("type") == "history"]
        count = len(history_msgs)
        if count == 0:
            return messages

        if count > 4:
            target = 4
        elif count > 2:
            target = 2
        else:
            target = 0

        if target == count:
            return messages

        to_remove = {idx for idx, _ in history_msgs[:-target]} if target > 0 else {idx for idx, _ in history_msgs}
        return [m for i, m in enumerate(messages) if i not in to_remove]

    def _trim_facts(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Strategy 3: Reduce facts to pinned-only, keeping is_permanent/user_explicit."""
        result: list[dict[str, Any]] = []
        for msg in messages:
            meta = msg.get("_meta", {})
            if meta.get("type") == "fact":
                pinned_keys = meta.get("pinned_keys", [])
                if not pinned_keys:
                    continue
                content = msg["content"]
                lines = content.split("\n")
                kept = [lines[0]]  # header
                for line in lines[1:]:
                    if any(line.strip().startswith(f"{pk}:") or f" {pk}:" in line for pk in pinned_keys):
                        kept.append(line)
                if len(kept) > 1:
                    result.append({**msg, "content": "\n".join(kept)})
            else:
                result.append(msg)
        return result

    def _trim_insights(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Strategy 4: Remove insight messages entirely."""
        return [m for m in messages if m.get("_meta", {}).get("type") != "insight"]

    def _hard_truncate_oldest(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Strategy 5: Hard truncate the longest non-critical message."""
        max_round = max(
            (m.get("_meta", {}).get("round", 0) for m in messages),
            default=0,
        )
        longest_idx = -1
        longest_len = 0
        for i, msg in enumerate(messages):
            meta = msg.get("_meta", {})
            if meta.get("type") in CRITICAL_TYPES:
                continue
            if meta.get("type") == "tool_result" and meta.get("round", 0) > 0:
                if meta["round"] >= max_round - 1:
                    continue
            content_len = len(msg.get("content", "") or "")
            if content_len > longest_len:
                longest_len = content_len
                longest_idx = i

        if longest_idx >= 0 and longest_len > MIN_TRUNCATION_CHARS:
            msg = messages[longest_idx]
            messages = list(messages)
            messages[longest_idx] = {
                **msg,
                "content": msg["content"][:MIN_TRUNCATION_CHARS] + "\n... (truncated to fit context window)",
            }

        return messages
