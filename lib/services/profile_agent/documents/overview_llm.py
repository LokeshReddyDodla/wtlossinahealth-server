"""Holistic patient overview narrative.

Given the deterministic link_groups + per-document summaries computed by
the linker and the upload pipeline, ask an LLM for a single short
narrative the patient and their doctor will both read on the dashboard.

This is the only LLM-dependent step in the overview rebuild — link group
membership and trends are computed deterministically; the LLM is only
asked to *describe* what the data already says.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List

from openai import AsyncOpenAI

from lib.schemas.profile_agent_documents import LinkGroup, OverviewNarrative

logger = logging.getLogger(__name__)

_MODEL = "gpt-4o-mini"
_MAX_TOKENS = 700

_SYSTEM_PROMPT = """You are summarizing a patient's medical document history for both the patient and their care provider.

You are given:
  * `documents`: chronological list of (document_date, category, summary_text).
  * `link_groups`: clinically related findings that recur across documents (e.g. the same lab repeated, an ongoing medication, a chronic diagnosis).

Return strict JSON:
{
  "summary_text": "<2-5 sentence overview of the patient's documented health history. Mention key trends (rising/falling labs), ongoing medications, and active diagnoses. Use plain language; no marketing tone.>",
  "key_observations": [
    "<short bullet, e.g. 'HbA1c trending down: 7.9 → 6.4 over the last 18 months'>",
    "<another bullet>"
  ]
}

Rules:
- Ground every claim in the provided data. Do NOT invent labs, diagnoses, or dates.
- If there is only one document, describe what it shows without speculating about trends.
- Keep it factual and structured. No greetings, no disclaimers.
- Return at most 6 bullets in `key_observations`.
- If there is no usable data, return {"summary_text": "No medical documents on file yet.", "key_observations": []}.
"""


def _serialize_overview_input(
    documents: List[Dict[str, Any]],
    link_groups: List[LinkGroup],
) -> str:
    docs = [
        {
            "document_date": _iso(d.get("document_date")),
            "category": d.get("category"),
            "summary_text": (d.get("summary_text") or "")[:1200],
        }
        for d in documents
    ]
    groups = []
    for g in link_groups:
        groups.append(
            {
                "name": g.name,
                "finding_type": g.finding_type,
                "code_system": g.code_system,
                "code": g.code,
                "occurrences": [
                    {
                        "observed_at": _iso(o.observed_at or o.document_date),
                        "value_numeric": o.value_numeric,
                        "value_text": o.value_text,
                        "unit": o.unit,
                    }
                    for o in g.occurrences
                ],
            }
        )
    return json.dumps({"documents": docs, "link_groups": groups})


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


async def generate_narrative(
    client: AsyncOpenAI,
    documents: List[Dict[str, Any]],
    link_groups: List[LinkGroup],
) -> OverviewNarrative:
    """Run a single JSON-mode LLM call and return the validated narrative.

    Returns a safe empty narrative on any failure — the caller still upserts
    the overview row so the deterministic link_groups + counts are visible.
    """
    if not documents:
        return OverviewNarrative(
            summary_text="No medical documents on file yet.",
            key_observations=[],
        )

    user_content = _serialize_overview_input(documents, link_groups)

    try:
        response = await client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            max_tokens=_MAX_TOKENS,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        raw = json.loads(content)
        return OverviewNarrative(
            summary_text=(raw.get("summary_text") or "").strip(),
            key_observations=[
                str(x).strip()
                for x in (raw.get("key_observations") or [])
                if str(x).strip()
            ][:6],
        )
    except json.JSONDecodeError:
        logger.warning("overview_llm: non-JSON response")
    except Exception:
        logger.exception("overview_llm: OpenAI call failed")

    return OverviewNarrative(summary_text="", key_observations=[])
