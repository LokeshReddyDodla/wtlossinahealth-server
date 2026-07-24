"""
Dashboard Help Agent — in-product helpline for doctors, care providers and admins.

Answers "how do I… / where is…" questions about USING the AiHealth dashboard,
with step-by-step navigation, and attaches a matching how-to video when one exists.

Design notes:
- The "brain" is two files in ./knowledge (system_prompt.md + knowledge_base.md) that
  devs edit directly — no DB, no redeploy of code logic to change content.
- Video selection is a separate, tiny classifier call (reliable + paraphrase-proof)
  rather than asking the answer model to tag itself.
- Built on the ai_foundation stack: uses self.gateway (ModelGateway) like other agents.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from uuid import uuid4

from lib.ai_foundation.agents.base import BaseAgent
from lib.ai_foundation.agents.state import AgentInput, AgentOutput
from lib.ai_foundation.models.registry import ModelTask

from .video_catalog import VIDEO_CATALOG, video_url

logger = logging.getLogger(__name__)

_KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"
_TEMPERATURE = 0.2
_MAX_TOKENS = 700
_MAX_TURNS = 12


def _load_brain() -> str:
    system_prompt = (_KNOWLEDGE_DIR / "system_prompt.md").read_text(encoding="utf-8")
    knowledge_base = (_KNOWLEDGE_DIR / "knowledge_base.md").read_text(encoding="utf-8")
    return (
        f"{system_prompt}\n\n"
        "# KNOWLEDGE BASE (your only source of truth about the dashboard)\n\n"
        f"{knowledge_base}"
    )


def _build_video_picker_prompt() -> str:
    return (
        "You match a user's question about the AiHealth dashboard to the single best "
        "how-to video, or to NONE if no video clearly fits.\n"
        "Reply with ONLY the video id exactly as listed, or the word NONE. "
        "No other text, no punctuation.\n\n"
        "Videos:\n"
        + "\n".join(f"- {vid}: {desc}" for vid, desc in VIDEO_CATALOG.items())
    )


class DashboardHelpAgent(BaseAgent):
    """Helpline agent: navigation answers + matching how-to video."""

    agent_id = "dashboard_help"

    def __init__(self, *, gateway, memory=None, prompts=None, event_bus=None) -> None:
        super().__init__(gateway=gateway, memory=memory, prompts=prompts, event_bus=event_bus)
        # Loaded once at startup; edit the files + restart to change content.
        self._system_message = _load_brain()
        self._video_picker_prompt = _build_video_picker_prompt()

    # -- Public API -----------------------------------------------------------

    async def run(self, input: AgentInput) -> AgentOutput:
        start = time.perf_counter()
        trace_id = input.context.trace_id or f"trc_{uuid4().hex[:16]}"
        self.gateway.set_langfuse_context(
            session_id=input.context.thread_id,
            user_id=input.context.user_id,
        )
        self.gateway.langfuse_trace_input(
            trace_id=trace_id, name="dashboard_help", input_text=input.message,
        )

        history = self._coerce_history(input.metadata.get("history"))
        messages = [{"role": "system", "content": self._system_message}, *history,
                    {"role": "user", "content": input.message}]

        try:
            response = await self.gateway.complete(
                messages=messages,
                task=ModelTask.RESPONSE_GENERATION,
                temperature=_TEMPERATURE,
                max_tokens=_MAX_TOKENS,
                trace_id=trace_id,
            )
            reply = (response.content or "").strip()
            cost_usd = response.cost.total_cost if getattr(response, "cost", None) else None
            model_id = getattr(response, "model_id", None)
        except Exception as exc:
            logger.exception("DashboardHelp answer failed: %s", exc)
            return AgentOutput(
                message="Sorry, something went wrong answering that. Please try again.",
                is_ready=False,
                trace_id=trace_id,
            )

        video_id = await self._pick_video(input.message, trace_id)
        v_url = video_url(video_id) if video_id else None

        latency_ms = int((time.perf_counter() - start) * 1000)
        self.gateway.langfuse_trace_output(trace_id=trace_id, output_text=reply)
        return AgentOutput(
            message=reply,
            trace_id=trace_id,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            model_id=model_id,
            data={"video_id": video_id, "video_url": v_url},
        )

    # -- Internals ------------------------------------------------------------

    async def _pick_video(self, user_message: str, trace_id: str) -> str | None:
        """Tiny classifier call: returns a valid video id for this question, or None."""
        try:
            resp = await self.gateway.complete(
                messages=[
                    {"role": "system", "content": self._video_picker_prompt},
                    {"role": "user", "content": user_message},
                ],
                task=ModelTask.CLASSIFICATION,
                temperature=0,
                max_tokens=12,
                trace_id=trace_id,
            )
            out = (resp.content or "").strip().lower()
        except Exception as exc:
            logger.warning("DashboardHelp video pick failed: %s", exc)
            return None

        if "none" in out:
            return None
        for vid in VIDEO_CATALOG:
            if vid in out:
                return vid
        return None

    @staticmethod
    def _coerce_history(raw) -> list[dict[str, str]]:
        """Accept [{role, content}, ...] from the client; keep recent, clean turns."""
        if not isinstance(raw, list):
            return []
        clean: list[dict[str, str]] = []
        for turn in raw[-_MAX_TURNS:]:
            if isinstance(turn, dict) and turn.get("role") in {"user", "assistant"} and turn.get("content"):
                clean.append({"role": turn["role"], "content": str(turn["content"])})
        return clean
