"""LLM intent extraction for the profile agent.

One model call per turn. Deterministic reducer consumes the result;
the LLM is never in charge of mutation.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from lib.schemas.profile_agent import GapFieldInfo, LLMAction, LLMResponse
from lib.services.profile_agent.prompts import build_system_prompt

logger = logging.getLogger(__name__)

_MODEL = "gpt-4o-mini"
_MAX_TOKENS = 400


async def extract_intent(
    client: AsyncOpenAI,
    messages: List[Dict[str, str]],
    *,
    mode: str,
    profile_context_json: Optional[str],
    next_field: Optional[GapFieldInfo],
    pending_draft: Dict[str, Any],
) -> LLMResponse:
    system = build_system_prompt(
        mode=mode,
        profile_context_json=profile_context_json,
        next_field=next_field,
        pending_draft=pending_draft,
    )
    llm_messages = [{"role": "system", "content": system}] + messages

    try:
        response = await client.chat.completions.create(
            model=_MODEL,
            messages=llm_messages,
            temperature=0.0,
            max_tokens=_MAX_TOKENS,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        raw = json.loads(content)
        actions: List[LLMAction] = []
        for a in raw.get("actions", []) or []:
            try:
                actions.append(LLMAction(**a))
            except Exception:
                logger.debug("dropping invalid LLM action: %s", a)
        return LLMResponse(actions=actions, reply=raw.get("reply", ""))
    except json.JSONDecodeError:
        logger.warning("LLM returned non-JSON; falling back to empty intent.")
        return LLMResponse(reply="Sorry, I didn't quite catch that. Could you rephrase?")
    except Exception:
        logger.exception("OpenAI call failed during profile-agent chat.")
        return LLMResponse(reply="I'm having trouble right now. Please try again shortly.")
