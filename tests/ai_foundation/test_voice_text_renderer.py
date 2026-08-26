from lib.ai_foundation.voice.text_renderer import MarkdownSpeechTextRenderer


def test_markdown_is_rendered_as_speech_text():
    renderer = MarkdownSpeechTextRenderer()

    spoken = renderer.render(
        "## Latest scan\n\n"
        "**Weight:** 72.7 kg\n\n"
        "- Review the [full report](https://example.com)\n"
        "- Compare `BMI` next time"
    )

    assert spoken == (
        "Latest scan\n"
        "Weight: 72.7 kg\n"
        "Review the full report\n"
        "Compare BMI next time"
    )
    assert "#" not in spoken
    assert "**" not in spoken
    assert "https://" not in spoken
