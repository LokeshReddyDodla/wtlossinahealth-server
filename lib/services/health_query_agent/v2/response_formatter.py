from __future__ import annotations

from .models import AnalysisSnapshot, IntentPlan, ResponseMode, RetrievalPlan


class ResponseFormatter:
    def format(
        self,
        *,
        intent_plan: IntentPlan,
        retrieval_plan: RetrievalPlan,
        analysis: AnalysisSnapshot,
    ) -> str:
        mode = intent_plan.response_mode
        if mode == ResponseMode.LIST:
            return self._format_list(analysis)
        if mode == ResponseMode.COMPARE:
            return self._format_compare(analysis)
        if mode == ResponseMode.EVALUATE:
            return self._format_evaluate(analysis)
        if mode == ResponseMode.RECOMMEND:
            return self._format_recommend(analysis)
        if mode == ResponseMode.CLARIFY:
            return self._format_clarify(intent_plan)
        return self._format_summarize(analysis)

    @staticmethod
    def _format_list(analysis: AnalysisSnapshot) -> str:
        summary = analysis.summary
        lines = ["Preferred render shape:", "Lead-in: one short sentence."]
        meals = summary.get("meals") or {}
        fitness = summary.get("fitness") or {}
        sleep = summary.get("sleep") or {}

        if meals:
            meal_names = meals.get("meal_names") or []
            lines.append("Bullets:")
            for meal_name in meal_names[:6]:
                lines.append(f"- {meal_name}")
        if fitness and fitness.get("steps") is not None:
            lines.append(f"- Steps: {fitness.get('steps')}")
        if sleep and sleep.get("duration_hours") is not None:
            lines.append(f"- Sleep: {sleep.get('duration_hours')} hours")
        if len(lines) == 2:
            lines.append("- No concrete records found in the structured analysis.")
        return "\n".join(lines)

    @staticmethod
    def _format_summarize(analysis: AnalysisSnapshot) -> str:
        summary = analysis.summary
        lines = ["Preferred render shape:", "Paragraph 1: short summary of the main pattern."]
        highlights = analysis.highlights[:3]
        if highlights:
            lines.append("Takeaway: " + "; ".join(highlights))
        if summary.get("meals"):
            meals = summary["meals"]
            lines.append(
                f"Meal anchor: {meals.get('count')} meals, {meals.get('total_calories')} kcal total."
            )
        if summary.get("fitness") and summary["fitness"].get("steps") is not None:
            lines.append(f"Fitness anchor: {summary['fitness'].get('steps')} steps.")
        if summary.get("sleep") and summary["sleep"].get("duration_hours") is not None:
            lines.append(
                f"Sleep anchor: {summary['sleep'].get('duration_hours')} hours."
            )
        return "\n".join(lines)

    @staticmethod
    def _format_evaluate(analysis: AnalysisSnapshot) -> str:
        lines = [
            "Preferred render shape:",
            "Sentence 1: direct verdict.",
            "Sentences 2-4: 2-4 concise supporting points grounded in the structured analysis.",
        ]
        if analysis.highlights:
            lines.append("Evidence anchors: " + "; ".join(analysis.highlights[:4]))
        return "\n".join(lines)

    @staticmethod
    def _format_compare(analysis: AnalysisSnapshot) -> str:
        lines = [
            "Preferred render shape:",
            "Sentence 1: compare the periods directly.",
            "Sentence 2: state the biggest delta.",
            "Sentence 3: one takeaway.",
        ]
        if analysis.highlights:
            lines.append("Comparison anchors: " + "; ".join(analysis.highlights[:3]))
        return "\n".join(lines)

    @staticmethod
    def _format_recommend(analysis: AnalysisSnapshot) -> str:
        lines = [
            "Preferred render shape:",
            "Give 1-3 concrete recommendations only.",
        ]
        if analysis.highlights:
            lines.append("Use these anchors: " + "; ".join(analysis.highlights[:3]))
        return "\n".join(lines)

    @staticmethod
    def _format_clarify(intent_plan: IntentPlan) -> str:
        return "\n".join(
            [
                "Preferred render shape:",
                "Ask one narrow follow-up question only.",
                f"Target response mode after clarification: {intent_plan.response_mode.value}.",
            ]
        )

    def render_no_data(
        self,
        *,
        intent_plan: IntentPlan,
        retrieval_plan: RetrievalPlan,
    ) -> str:
        domain_label = self._domain_label(intent_plan)
        scope = self._scope_label(intent_plan)
        if "mongo_report_fetch" in retrieval_plan.tool_chain:
            return f"I couldn't find any {domain_label} data for {scope}."
        if intent_plan.response_mode == ResponseMode.CLARIFY:
            return f"I don't have enough context to answer that yet. What {domain_label} data do you want me to check?"
        return f"I couldn't find enough {domain_label} data to answer that confidently for {scope}."

    def render_fallback_text(
        self,
        *,
        intent_plan: IntentPlan,
        analysis: AnalysisSnapshot,
        warnings: list[str] | None = None,
    ) -> str:
        warnings = warnings or []
        summary = analysis.summary
        highlights = analysis.highlights[:3]
        if intent_plan.response_mode == ResponseMode.LIST:
            meals = (summary.get("meals") or {}).get("meal_names") or []
            if meals:
                return "Here are the records I found: " + ", ".join(meals[:4]) + "."
            return self.render_no_data(intent_plan=intent_plan, retrieval_plan=RetrievalPlan())
        if intent_plan.response_mode == ResponseMode.COMPARE:
            if highlights:
                return "Here’s the main comparison: " + "; ".join(highlights[:2]) + "."
            return "I found data for the comparison, but not enough signal to state a strong difference."
        if intent_plan.response_mode == ResponseMode.EVALUATE:
            if highlights:
                return "Overall, " + "; ".join(highlights[:3]) + "."
            return "I found some data, but not enough signal to give a confident evaluation."
        if intent_plan.response_mode == ResponseMode.RECOMMEND:
            if highlights:
                return "Based on what I found, focus on this first: " + highlights[0] + "."
            return "I need more concrete data before giving a recommendation."

        anchors: list[str] = []
        meals = summary.get("meals") or {}
        fitness = summary.get("fitness") or {}
        sleep = summary.get("sleep") or {}
        if meals.get("count"):
            anchors.append(f"{meals['count']} meals logged")
        if fitness.get("steps") is not None:
            anchors.append(f"{fitness['steps']} steps")
        if sleep.get("duration_hours") is not None:
            anchors.append(f"{sleep['duration_hours']} hours of sleep")
        if anchors:
            text = "Summary: " + ", ".join(anchors[:3]) + "."
        elif highlights:
            text = "Summary: " + "; ".join(highlights[:3]) + "."
        else:
            text = "I found some data, but not enough to summarize it cleanly."
        if warnings:
            text += " Some optional context was unavailable."
        return text

    @staticmethod
    def _domain_label(intent_plan: IntentPlan) -> str:
        if not intent_plan.domains:
            return "health"
        if len(intent_plan.domains) == 1:
            return intent_plan.domains[0].value
        return " and ".join(domain.value for domain in intent_plan.domains[:3])

    @staticmethod
    def _scope_label(intent_plan: IntentPlan) -> str:
        return intent_plan.date_scope_label or "the requested period"
