"""Voice mirrors the SPOKEN language — detection → agent override → TTS.

Chat follows the stored preference; voice follows the voice. Every hop of
that rule is exercised here: language normalization, TTS speakability
gating, session mirroring, agent metadata override, and per-request TTS.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.ai_foundation.voice.orchestrator import _normalize_spoken_language


def test_normalize_spoken_language():
    assert _normalize_spoken_language("hi-IN") == "hi"
    assert _normalize_spoken_language("hi") == "hi"
    assert _normalize_spoken_language("hindi") == "hi"
    assert _normalize_spoken_language("English") == "en"
    assert _normalize_spoken_language("urdu") == "ur"
    assert _normalize_spoken_language("unknown") is None
    assert _normalize_spoken_language("") is None
    assert _normalize_spoken_language(None) is None
    assert _normalize_spoken_language("no-such-language-name") is None


def test_sarvam_tts_language_support_and_per_request_code():
    from lib.ai_foundation.voice.config import VoiceSettings
    from lib.ai_foundation.voice.tts import SarvamTextToSpeech

    tts = SarvamTextToSpeech.__new__(SarvamTextToSpeech)
    tts._settings = VoiceSettings(SARVAM_TTS_LANGUAGE="en-IN")

    assert tts.supports_language("hi") is True
    assert tts.supports_language("ta") is True
    # STT understands Urdu; Sarvam TTS cannot speak it — must be gated out
    assert tts.supports_language("ur") is False

    assert tts._resolve_language("hi") == "hi-IN"
    assert tts._resolve_language("ta-IN") == "ta-IN"
    assert tts._resolve_language(None) == "en-IN"  # config default


def test_openai_tts_accepts_any_language():
    from lib.ai_foundation.voice.tts import OpenAITextToSpeech

    tts = OpenAITextToSpeech.__new__(OpenAITextToSpeech)
    assert tts.supports_language("ur") is True  # multilingual voices


@pytest.mark.asyncio
async def test_filler_cache_is_language_scoped():
    from lib.ai_foundation.voice.config import VoiceSettings
    from lib.ai_foundation.voice.tts import SarvamTextToSpeech

    tts = SarvamTextToSpeech.__new__(SarvamTextToSpeech)
    tts._settings = VoiceSettings()
    tts._filler_cache = type(tts)._filler_cache = __import__("collections").OrderedDict()
    calls: list = []

    async def fake_full(text, language=None):
        calls.append(language)
        return f"{language}:{text}".encode()

    tts._synthesize_full = fake_full
    en = await tts.synthesize("Let me check.", "en")
    hi = await tts.synthesize("Let me check.", "hi")
    assert en != hi  # same text, different language → different audio
    assert calls == ["en", "hi"]
    # second hit per language comes from cache
    assert await tts.synthesize("Let me check.", "hi") == hi
    assert calls == ["en", "hi"]


def test_agent_effective_language_voice_overrides_preference():
    from lib.ai_foundation.agents.health_query.agent import HealthQueryAgent
    from lib.ai_foundation.agents.state import AgentContext as ReqCtx, AgentInput

    ctx = MagicMock()
    ctx.response_language = "hi"  # stored preference

    voice_input = AgentInput(message="m", context=ReqCtx(
        patient_id="p1", user_id="p1", user_role="patient", thread_id="t",
        patient_ids=["p1"], metadata={"output_mode": "voice", "voice_language": "ta"},
    ))
    chat_input = AgentInput(message="m", context=ReqCtx(
        patient_id="p1", user_id="p1", user_role="patient", thread_id="t",
        patient_ids=["p1"], metadata={},
    ))

    # voice: the utterance wins over the preference
    assert HealthQueryAgent._effective_language(voice_input, ctx) == "ta"
    # chat: preference wins
    assert HealthQueryAgent._effective_language(chat_input, ctx) == "hi"


def test_voice_prompt_gets_language_instruction():
    from lib.ai_foundation.agents.health_query.agent import HealthQueryAgent
    from lib.ai_foundation.agents.state import AgentContext as ReqCtx, AgentInput

    agent = HealthQueryAgent.__new__(HealthQueryAgent)
    agent._prompts_registered = False
    agent.prompts = None  # force local prompt dir registration below

    from lib.ai_foundation.prompts.registry import PromptRegistry
    agent.prompts = PromptRegistry()

    voice_input = AgentInput(message="m", context=ReqCtx(
        patient_id="p1", user_id="p1", user_role="patient", thread_id="t",
        patient_ids=["p1"], metadata={"output_mode": "voice", "voice_language": "hi"},
    ))
    _, response = agent._get_reasoning_prompts(voice_input, "hi")
    assert "Hindi" in response and "reply ENTIRELY in" in response
    # markers/markdown language rules are the CHAT instruction — voice gets
    # the speakable variant without them
    assert "[[BUBBLE]]" not in response.split("Response Language")[1].split("##")[0]

    _, response_en = agent._get_reasoning_prompts(voice_input, "en")
    assert "reply ENTIRELY in" not in response_en
