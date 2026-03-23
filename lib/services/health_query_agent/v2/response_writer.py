from __future__ import annotations

import json

from .models import AnalysisSnapshot, IntentPlan, ResponseDraft, RetrievalPlan
from .playbook_loader import PlaybookLoader
from .response_formatter import ResponseFormatter


class ResponseWriterSupport:
    def __init__(
        self,
        playbook_loader: PlaybookLoader | None = None,
        response_formatter: ResponseFormatter | None = None,
    ):
        self.playbook_loader = playbook_loader or PlaybookLoader()
        self.response_formatter = response_formatter or ResponseFormatter()

    def build_draft(self, intent_plan: IntentPlan, retrieval_plan: RetrievalPlan, analysis: AnalysisSnapshot) -> ResponseDraft:
        playbooks = [
            self.playbook_loader.load_by_name(name)
            for name in retrieval_plan.playbooks
        ]
        playbook_sections = [
            f"Playbook {playbook.name}:\n{playbook.body.strip()}"
            for playbook in playbooks
            if playbook is not None
        ]
        mode_instructions = self._mode_instructions(intent_plan.response_mode)
        retrieval_instructions = self._retrieval_instructions(retrieval_plan)
        style_notes = self._style_notes(intent_plan.response_mode)
        formatted_context = self.response_formatter.format(
            intent_plan=intent_plan,
            retrieval_plan=retrieval_plan,
            analysis=analysis,
        )
        system_addendum = "\n\n".join(
            [
                "Use the structured analysis as the primary source of truth.",
                "Be conversational and concise. Answer first. Prefer short paragraphs over bullets unless the user explicitly asked for a list.",
                "Do not repeat large pattern recaps from earlier turns unless the new analysis materially changes the conclusion.",
                f"Response mode: {intent_plan.response_mode.value}.",
                mode_instructions,
                retrieval_instructions,
                "Preferred response scaffold:\n" + formatted_context,
                *(playbook_sections or []),
            ]
        )
        analysis_payload = json.dumps(analysis.model_dump(mode="json"), default=str)
        return ResponseDraft(
            system_addendum=system_addendum,
            analysis_payload=analysis_payload,
            formatted_context=formatted_context,
            style_notes=style_notes,
        )

    @staticmethod
    def _mode_instructions(response_mode) -> str:
        mode_map = {
            "list": (
                "Formatting contract: for list responses, give a one-line lead-in and then compact bullets. "
                "Do not add coaching unless the user explicitly asked for analysis."
            ),
            "summarize": (
                "Formatting contract: for summarize responses, use one short paragraph and one short takeaway. "
                "Avoid dumping every record."
            ),
            "evaluate": (
                "Formatting contract: for evaluate responses, start with the verdict, then give 2-4 concise supporting points. "
                "Keep judgment grounded in the analysis."
            ),
            "compare": (
                "Formatting contract: for compare responses, compare period A vs period B directly, surface the key delta, "
                "and end with one takeaway."
            ),
            "recommend": (
                "Formatting contract: for recommend responses, give 1-3 concrete actions only. "
                "Avoid broad generic advice."
            ),
            "clarify": (
                "Formatting contract: for clarify responses, ask one narrow follow-up question and stop."
            ),
        }
        return mode_map.get(
            getattr(response_mode, "value", str(response_mode)),
            "Formatting contract: keep the answer concise and direct.",
        )

    @staticmethod
    def _retrieval_instructions(retrieval_plan: RetrievalPlan) -> str:
        if "mongo_report_fetch" in retrieval_plan.tool_chain and "qdrant_search" not in retrieval_plan.tool_chain:
            return (
                "Data source contract: this answer is based on exact report fetches. "
                "Present findings as concrete records or aggregates, not fuzzy semantic matches."
            )
        if "qdrant_search" in retrieval_plan.tool_chain and "mongo_report_fetch" not in retrieval_plan.tool_chain:
            return (
                "Data source contract: this answer is based on retrieved semantic payloads. "
                "Synthesize carefully and avoid pretending the evidence is more exact than it is."
            )
        if "mongo_report_fetch" in retrieval_plan.tool_chain and "qdrant_search" in retrieval_plan.tool_chain:
            return (
                "Data source contract: exact report data should take precedence over semantic retrieval when they overlap. "
                "Use semantic results only for supporting context."
            )
        return "Data source contract: use the structured analysis only."

    @staticmethod
    def _style_notes(response_mode) -> list[str]:
        base = [
            "Avoid decorative separators and excessive bolding.",
            "Offer at most one optional next step.",
        ]
        mode_value = getattr(response_mode, "value", str(response_mode))
        if mode_value == "list":
            return ["Use compact bullets for multiple records.", "Keep the intro to one sentence.", *base]
        if mode_value == "compare":
            return ["Keep comparison to 3-5 sentences total.", "Make the key delta explicit.", *base]
        if mode_value == "evaluate":
            return ["Default to 3-5 sentences.", "Lead with the verdict.", *base]
        if mode_value == "summarize":
            return ["Default to 2-4 sentences.", "Focus on the main pattern only.", *base]
        if mode_value == "recommend":
            return ["Default to 2-4 sentences.", "Keep recommendations concrete and limited.", *base]
        if mode_value == "clarify":
            return ["Ask one question only.", *base]
        return ["Default to 2-5 sentences.", *base]
