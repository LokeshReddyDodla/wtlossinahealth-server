"""Patient-facing translation for the preferred-AI-language feature.

Invariant: the user always sees AI text in their preferred language, and an
English copy of the same text always exists. This service is the only
translation path — chat audit copies (preferred → en) and proactive delivery
copies (en → preferred) both go through ``translate``.

Medical text: fidelity beats fluency. Deterministic post-checks verify that
every number survived and structural markers ([[BUBBLE]]/[[AWAIT:*]]) are
intact; a failed check retries once, then falls back to the source text —
we never show a corrupted translation.
"""

from __future__ import annotations

import logging
import re

from lib.ai_foundation.models.gateway import ModelGateway
from lib.ai_foundation.models.registry import ModelTask
from lib.core.types import ai_language_name

logger = logging.getLogger(__name__)

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_MARKER_RE = re.compile(r"\[\[(?:BUBBLE|AWAIT:[a-z_]+)\]\]")

_SYSTEM_PROMPT = """You are a medical translator for a diabetes-care companion app.

Translate the user's message from {source_name} to {target_name}.

Hard rules — violating any of these makes the translation unusable:
1. Every number stays EXACTLY as written: values, units (mg/dL, g, kcal, hours, %), dates, times. Never convert, round, or spell out numbers.
2. Markdown structure survives verbatim: headings, **bold**, bullet lists, tables (translate cell text, never the table syntax), emoji, code fences.
3. Any [[BUBBLE]] or [[AWAIT:...]] token is copied through unchanged, on its own line, same position.
4. Translate everything else faithfully — no added advice, no dropped sentences, no summarizing.
5. Register: warm, caring companion — the tone of a friend who knows your health, not a formal document.{register_extra}

Output ONLY the translation. No preamble, no notes."""

_REGISTER_EXTRA = {
    "hi-Latn": "\n6. Hinglish means Hindi written in roman script, the way people casually text (\"aapka glucose aaj stable raha\"). Keep common English health words (glucose, protein, sleep) as-is where natural.",
}


class TranslationService:
    """LLM translation with deterministic fidelity checks."""

    _CACHE_MAX = 256

    def __init__(self, gateway: ModelGateway) -> None:
        self._gateway = gateway
        # For fixed UI strings (chip labels, acks): tiny recurring set, so
        # each (lang, text) pays the LLM once per process.
        self._cache: dict[tuple[str, str], str] = {}

    async def translate_cached(
        self, text: str, target_lang: str, *, source_lang: str = "en",
    ) -> str:
        """``translate`` with an in-memory cache — ONLY for fixed strings
        (labels, canned acks), never for patient-specific content."""
        key = (target_lang, text)
        if key in self._cache:
            return self._cache[key]
        result = await self.translate(text, target_lang, source_lang=source_lang)
        # Don't cache fallbacks — a transient provider failure shouldn't
        # pin the English text for the process lifetime.
        if result != text or target_lang == source_lang:
            if len(self._cache) >= self._CACHE_MAX:
                self._cache.clear()
            self._cache[key] = result
        return result

    async def translate(
        self,
        text: str,
        target_lang: str,
        *,
        source_lang: str = "en",
        trace_id: str | None = None,
    ) -> str:
        """Translate ``text``; returns the source text unchanged when the
        languages match, the text is empty, or the translation fails checks."""
        if not text or not text.strip() or target_lang == source_lang:
            return text

        target_name = ai_language_name(target_lang)
        source_name = ai_language_name(source_lang)
        system = _SYSTEM_PROMPT.format(
            source_name=source_name,
            target_name=target_name,
            register_extra=_REGISTER_EXTRA.get(target_lang, ""),
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ]

        for attempt in (1, 2):
            try:
                response = await self._gateway.complete(
                    messages=messages,
                    task=ModelTask.TRANSLATION,
                    temperature=0.2,
                    trace_id=trace_id,
                )
                candidate = (response.content or "").strip()
                problem = self._fidelity_problem(text, candidate)
                if problem is None:
                    return candidate
                logger.warning(
                    "Translation fidelity check failed (attempt %d, %s→%s): %s",
                    attempt, source_lang, target_lang, problem,
                )
            except Exception as exc:
                logger.warning(
                    "Translation call failed (attempt %d, %s→%s): %s",
                    attempt, source_lang, target_lang, exc,
                )
        return text

    @staticmethod
    def _fidelity_problem(source: str, candidate: str) -> str | None:
        """Deterministic checks; returns a description of the first problem."""
        if not candidate:
            return "empty translation"
        missing = [n for n in set(_NUMBER_RE.findall(source)) if n not in candidate]
        if missing:
            return f"numbers missing: {sorted(missing)[:5]}"
        src_markers = sorted(_MARKER_RE.findall(source))
        out_markers = sorted(_MARKER_RE.findall(candidate))
        if src_markers != out_markers:
            return f"markers changed: {src_markers} -> {out_markers}"
        return None
