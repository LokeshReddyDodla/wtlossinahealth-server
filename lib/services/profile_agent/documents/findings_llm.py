"""LLM-based extraction of structured medical findings from a document's
already-extracted text.

The existing `PatientDocumentService` upload pipeline runs
`FileContentExtractorService.extract` to get plain text (and OCR
fallback for image-only PDFs), then asks an LLM for a free-text
clinical summary. This module runs a follow-up JSON-mode LLM call
that turns the same text into a structured `findings[]` array — labs
with values + units, medications with dosage, diagnoses, vitals,
imaging notes — usable for cross-document interlinking.
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional

from openai import AsyncOpenAI

from lib.schemas.profile_agent_documents import Finding, FindingsExtraction
from lib.services.profile_agent.documents.linker import normalize_name

logger = logging.getLogger(__name__)

_MODEL = "gpt-4o-mini"
_MAX_TOKENS = 2000
_MAX_TEXT_CHARS = 24000  # ~6k tokens of input; cheap + within context window

_SYSTEM_PROMPT = """You extract structured medical findings from the document text below.

Return strict JSON matching this schema:
{
  "findings": [
    {
      "finding_type": "lab" | "medication" | "diagnosis" | "vital" | "imaging" | "note",
      "code_system": "loinc" | "rxnorm" | "icd10" | "snomed" | null,
      "code": "<string or null>",
      "name": "<human-readable name, e.g. 'HbA1c', 'Metformin', 'Type 2 diabetes mellitus'>",
      "value_numeric": <number or null>,
      "value_text": "<string or null>",
      "unit": "<string or null>",
      "reference_range_low": <number or null>,
      "reference_range_high": <number or null>,
      "observed_at": "<ISO 8601 datetime or null>"
    }
  ]
}

Rules:
- Populate `code_system` + `code` ONLY if you are confident (LOINC for labs, RxNorm for medications, ICD-10 or SNOMED for diagnoses). If you are unsure, leave both null — downstream matches by normalized name.
- Use `value_numeric` for numeric lab/vital results and put the unit in `unit`. Use `value_text` for non-numeric findings ("positive", "negative", "Type 2 diabetes mellitus", "500 mg twice daily").
- `observed_at` should be the date/time the measurement or event was recorded. Use ISO 8601 (YYYY-MM-DDTHH:MM:SS) when known; null otherwise.
- Skip fluffy narrative content; emit one entry per discrete clinical fact.
- Do NOT invent codes, values, or dates that are not in the source text.
- If no clinical findings are extractable, return {"findings": []}.
"""


async def extract_findings(
    client: AsyncOpenAI,
    text_raw: str,
    summary_text: Optional[str] = None,
) -> List[Finding]:
    """Run a single JSON-mode LLM call and return validated Finding rows.

    Returns an empty list on any failure (logged) — the caller decides
    whether to mark the document as `failed` or just `parsed` with no
    findings (e.g. for purely narrative notes).
    """
    if not text_raw or not text_raw.strip():
        return []

    truncated = text_raw[:_MAX_TEXT_CHARS]
    user_content = (
        (f"Document summary:\n{summary_text}\n\n" if summary_text else "")
        + f"Document text:\n{truncated}"
    )

    try:
        response = await client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
            max_tokens=_MAX_TOKENS,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        raw = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("findings_llm: non-JSON response, returning no findings")
        return []
    except Exception:
        logger.exception("findings_llm: OpenAI call failed")
        return []

    findings: List[Finding] = []
    for entry in raw.get("findings") or []:
        try:
            name = (entry.get("name") or "").strip()
            if not name:
                continue
            entry["name"] = name
            entry["name_normalized"] = normalize_name(name)
            findings.append(Finding(**entry))
        except Exception as e:
            logger.debug("findings_llm: dropping invalid finding %s: %s", entry, e)

    try:
        FindingsExtraction(findings=findings)
    except Exception:
        logger.exception("findings_llm: schema validation failed")
        return []

    return findings
