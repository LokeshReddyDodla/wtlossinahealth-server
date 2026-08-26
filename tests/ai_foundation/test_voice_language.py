"""Voice mirrors the SPOKEN language — detection → agent override → TTS.

Chat follows the stored preference; voice follows the voice. Every hop of
that rule is exercised here: language normalization, TTS speakability
gating, session mirroring, agent metadata override, and per-request TTS.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from lib.ai_foundation.voice.orchestrator import _normalize_spoken_language
from lib.ai_foundation.voice.text_renderer import MarkdownSpeechTextRenderer


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


@pytest.mark.asyncio
async def test_handle_utterance_real_path_mirrors_spoken_language():
    """Executes the REAL orchestrator pipeline with a Hindi utterance:
    detected language must reach the agent (metadata.voice_language),
    the TTS (per-request language), and the session state."""
    from lib.ai_foundation.voice.config import VoiceSettings
    from lib.ai_foundation.voice.orchestrator import VoiceOrchestrator
    from lib.ai_foundation.voice.session import VoiceSession

    settings = VoiceSettings()

    stt_result = MagicMock()
    stt_result.text = "मेरा ग्लूकोज़ कैसा है?"
    stt_result.language = "hi-IN"
    stt_result.duration_seconds = 2.0
    stt = MagicMock()
    stt.transcribe = AsyncMock(return_value=stt_result)

    tts = MagicMock()
    tts.supports_language = MagicMock(return_value=True)
    spoken: list[tuple[str, str | None]] = []

    async def fake_stream(text, language=None):
        spoken.append((text[:20], language))
        yield b"\x00" * 10

    tts.synthesize_stream = MagicMock(side_effect=fake_stream)

    captured_inputs = []

    async def fake_run_stream(agent_input):
        captured_inputs.append(agent_input)
        yield 'event: done\ndata: {"data": {"full_response": "आपका ग्लूकोज़ स्थिर है।"}}\n\n'

    agent = MagicMock()
    agent.run_stream = MagicMock(side_effect=fake_run_stream)

    orch = VoiceOrchestrator(
        stt=stt, tts=tts, agent=agent,
        patient_resolver=AsyncMock(),
        speech_text_renderer=MarkdownSpeechTextRenderer(), settings=settings,
    )
    session = VoiceSession(
        user_id="p1", patient_id="p1", thread_id="bot:patient:p1", settings=settings,
    )
    sent_json, sent_bytes = [], []

    async def send_json(d): sent_json.append(d)
    async def send_bytes(b): sent_bytes.append(b)

    await orch.handle_utterance(session, b"audio", send_json=send_json, send_bytes=send_bytes)

    # detected hi-IN → normalized hi → agent override + TTS language + session
    assert captured_inputs[0].context.metadata["voice_language"] == "hi"
    assert session.language == "hi"
    response_speaks = [lang for text, lang in spoken if "ग्लूकोज़" in text or lang]
    assert ("आपका ग्लूकोज़ स्थिर है।"[:20], "hi") in spoken
    assert sent_bytes, "audio must have streamed"


@pytest.mark.asyncio
async def test_handle_utterance_unspeakable_language_falls_back():
    """Urdu on a TTS that can't voice it: reply language falls back to the
    session seed instead of erroring mid-conversation."""
    from lib.ai_foundation.voice.config import VoiceSettings
    from lib.ai_foundation.voice.orchestrator import VoiceOrchestrator
    from lib.ai_foundation.voice.session import VoiceSession

    settings = VoiceSettings()
    stt_result = MagicMock()
    stt_result.text = "salaam"
    stt_result.language = "ur"
    stt_result.duration_seconds = 1.0
    stt = MagicMock()
    stt.transcribe = AsyncMock(return_value=stt_result)

    tts = MagicMock()
    tts.supports_language = MagicMock(side_effect=lambda lang: lang != "ur")

    async def fake_stream(text, language=None):
        yield b"\x00"

    tts.synthesize_stream = MagicMock(side_effect=fake_stream)

    captured = []

    async def fake_run_stream(agent_input):
        captured.append(agent_input)
        yield 'event: done\ndata: {"data": {"full_response": "ok"}}\n\n'

    agent = MagicMock()
    agent.run_stream = MagicMock(side_effect=fake_run_stream)

    orch = VoiceOrchestrator(
        stt=stt, tts=tts, agent=agent,
        patient_resolver=AsyncMock(),
        speech_text_renderer=MarkdownSpeechTextRenderer(), settings=settings,
    )
    session = VoiceSession(
        user_id="p1", patient_id="p1", thread_id="t", settings=settings,
    )
    session.language = "en"  # seed

    async def send(_): ...
    await orch.handle_utterance(session, b"a", send_json=send, send_bytes=send)

    assert captured[0].context.metadata["voice_language"] == "en"
    assert session.language == "en"
