"""Weekly agentic loop that composes plans and pushes coaching cards."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from decouple import config

from lib.schemas.weightloss_agent.coach import (
    CoachActionRequest,
    CoachActionResponse,
)
from lib.schemas.weightloss_agent.plan import (
    PlanGenerateRequest,
    PlanSnapshot,
)
from lib.services.weightloss_agent.analytics_service import AnalyticsService
from lib.services.weightloss_agent.coach_messenger_service import (
    CoachMessengerService,
)
from lib.services.weightloss_agent.plan_composer_service import (
    PlanComposerService,
)


class AgenticOrchestrator:
    def __init__(
        self,
        plan_composer_service: PlanComposerService,
        coach_messenger_service: CoachMessengerService,
        analytics_service: AnalyticsService,
    ) -> None:
        self.plan_composer_service = plan_composer_service
        self.coach_messenger_service = coach_messenger_service
        self.analytics_service = analytics_service
        self.is_enabled = True

    async def run_weekly_cycle(self, user_id: UUID) -> Dict[str, Optional[str]]:
        if not self.is_enabled:
            return {"status": "disabled"}

        previous_plan = await self.plan_composer_service.get_current_plan(
            user_id
        )
        plan_response = await self.plan_composer_service.generate_plan(
            PlanGenerateRequest(user_id=user_id)
        )
        plan = plan_response.plan_snapshot if plan_response else None

        coach_result: Optional[CoachActionResponse] = None
        if plan:
            coach_result = await self.coach_messenger_service.act(
                CoachActionRequest(
                    user_id=user_id,
                    trigger="weekly_agentic_cycle",
                    context_tags=["agentic", "weekly"],
                    plan_id=plan.plan_id,
                )
            )

        await self._record_audit(
            previous_plan=previous_plan,
            new_plan=plan,
            coach_result=coach_result,
        )

        return {
            "status": "completed",
            "plan_id": str(plan.plan_id) if plan else None,
        }

    async def _record_audit(
        self,
        previous_plan: Optional[PlanSnapshot],
        new_plan: Optional[PlanSnapshot],
        coach_result: Optional[CoachActionResponse],
    ) -> None:
        evidence_refs = []
        if previous_plan:
            evidence_refs.append(
                {"type": "plan_snapshot", "plan_id": str(previous_plan.plan_id)}
            )
        if new_plan:
            evidence_refs.append(
                {"type": "plan_snapshot", "plan_id": str(new_plan.plan_id)}
            )
        if coach_result and coach_result.cards:
            evidence_refs.append(
                {
                    "type": "coach_cards",
                    "card_ids": [str(card.card_id) for card in coach_result.cards],
                }
            )

        await self.analytics_service.record_audit_trace(
            {
                "previous_plan_id": str(previous_plan.plan_id)
                if previous_plan
                else None,
                "new_plan_id": str(new_plan.plan_id) if new_plan else None,
                "change_reason": "weekly_agentic_cycle",
                "evidence_refs": evidence_refs,
            }
        )
