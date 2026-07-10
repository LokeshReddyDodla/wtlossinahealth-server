"""TranslationService + preferred-AI-language plumbing.

The invariant under test: users see their preferred language, an English
copy always exists, and a corrupted translation is never shown.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lib.ai_foundation.translation.service import TranslationService


def _gateway(*contents: str):
    gw = MagicMock()
    responses = [MagicMock(content=c) for c in contents]
    gw.complete = AsyncMock(side_effect=responses)
    return gw


@pytest.mark.asyncio
async def test_same_language_is_noop_without_llm_call():
    gw = _gateway()
    svc = TranslationService(gw)
    assert await svc.translate("hello", "en", source_lang="en") == "hello"
    assert await svc.translate("", "hi") == ""
    gw.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_good_translation_passes_checks():
    gw = _gateway("आपका ग्लूकोज़ 118 mg/dL रहा")
    svc = TranslationService(gw)
    out = await svc.translate("Your glucose was 118 mg/dL", "hi")
    assert out == "आपका ग्लूकोज़ 118 mg/dL रहा"
    assert gw.complete.await_count == 1


@pytest.mark.asyncio
async def test_dropped_number_retries_then_falls_back_to_source():
    gw = _gateway("sab theek hai", "ab bhi bina number ke")
    svc = TranslationService(gw)
    out = await svc.translate("Average was 118 mg/dL", "hi-Latn")
    assert out == "Average was 118 mg/dL"  # never show a corrupted translation
    assert gw.complete.await_count == 2  # one retry


@pytest.mark.asyncio
async def test_marker_mutation_rejected():
    gw = _gateway("pehla hissa\n\ndoosra hissa", "pehla [[BUBBLE]] doosra")
    svc = TranslationService(gw)
    out = await svc.translate("part one [[BUBBLE]] part two", "hi-Latn")
    assert out == "pehla [[BUBBLE]] doosra"  # retry produced intact markers


@pytest.mark.asyncio
async def test_gateway_exception_falls_back_to_source():
    gw = MagicMock()
    gw.complete = AsyncMock(side_effect=RuntimeError("provider down"))
    svc = TranslationService(gw)
    assert await svc.translate("Take 500 mg", "hi") == "Take 500 mg"


@pytest.mark.asyncio
async def test_attach_translation_targets_specific_turn():
    from lib.ai_foundation.agents.core.persistence_service import PersistenceService

    mem = MagicMock()
    mem.update_turn_metadata_by_id = AsyncMock(return_value=True)
    svc = PersistenceService(memory=mem, gateway=MagicMock())
    await svc.attach_translation(
        turn_id="oid123", language="hi", translations={"en": "the english copy"},
    )
    mem.update_turn_metadata_by_id.assert_awaited_once_with(
        "oid123", {"language": "hi", "translations": {"en": "the english copy"}},
    )
    # no id = no write — never fall back to "latest turn" (race magnet)
    await svc.attach_translation(turn_id=None, language="hi", translations={"en": "x"})
    assert mem.update_turn_metadata_by_id.await_count == 1


def test_unknown_await_entity_stripped_but_not_registered():
    from lib.ai_foundation.agents.core.bubbles import AWAIT_ENTITY_TYPES, extract_await

    # hallucinated entity: marker never reaches the user, no pending recorded
    clean, entity = extract_await("Log it and I'll check. [[AWAIT:water]]")
    assert "[[AWAIT" not in clean and entity is None
    # only fulfillable entities are allowed (each has a real event producer)
    assert set(AWAIT_ENTITY_TYPES) == {"meal", "smbg", "symptom"}


@pytest.mark.asyncio
async def test_continuation_turn_carries_english_original():
    from tests.ai_foundation.test_chat_continuation import _memory, _summary
    from lib.workers.tasks.proactive_monitor.event_scan import _consume_pending_request

    mem = _memory(_summary("meal"))
    with patch("lib.workers.tasks.proactive_monitor.event_scan.container") as c:
        c.resolve.return_value = mem
        ok = await _consume_pending_request(
            "bot:patient:p1", "meal", "हिंदी में विश्लेषण",
            language="hi", english_body="Analysis in English",
        )
    assert ok is True
    turn = mem.append_turns_batch.await_args.args[1][0]
    assert turn.content == "हिंदी में विश्लेषण"
    assert turn.metadata["language"] == "hi"
    assert turn.metadata["translations"] == {"en": "Analysis in English"}


def test_ack_body_english_canonical():
    from lib.workers.tasks.proactive_monitor.event_scan import _ack_body

    assert "Got your meal" in _ack_body("meal")
    # unknown entity never KeyErrors
    assert _ack_body("unknown_thing")
    assert _ack_body(None)


@pytest.mark.asyncio
async def test_translate_cached_hits_llm_once_per_string():
    gw = _gateway("खाना लॉग करें", "should not be used")
    svc = TranslationService(gw)
    first = await svc.translate_cached("Log a meal", "hi")
    second = await svc.translate_cached("Log a meal", "hi")
    assert first == second == "खाना लॉग करें"
    assert gw.complete.await_count == 1


@pytest.mark.asyncio
async def test_translate_cached_never_caches_fallbacks():
    gw = MagicMock()
    gw.complete = AsyncMock(side_effect=RuntimeError("provider down"))
    svc = TranslationService(gw)
    assert await svc.translate_cached("Log sleep", "hi") == "Log sleep"
    assert svc._cache == {}  # transient failure must not pin English
