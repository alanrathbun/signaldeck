import pytest

from signaldeck.ai.summarizer import ActivitySummarizer, format_activity_for_llm


def test_format_activity_for_llm():
    """Formats activity entries into a prompt string."""
    entries = [
        {"frequency_mhz": 98.5, "protocol": "fm", "result_type": "voice", "summary": "FM station", "count": 5},
        {"frequency_mhz": 433.92, "protocol": "rtl433", "result_type": "data", "summary": "Temperature sensor", "count": 12},
    ]
    text = format_activity_for_llm(entries, hours=6)
    assert "98.5" in text
    assert "433.92" in text
    assert "6 hours" in text or "6h" in text


def test_summarizer_creates_prompt():
    """Summarizer creates a valid prompt for the LLM."""
    summarizer = ActivitySummarizer()
    entries = [
        {"frequency_mhz": 162.4, "protocol": "weather_radio", "result_type": "voice", "summary": "NOAA Weather", "count": 3},
    ]
    prompt = summarizer.build_prompt(entries, hours=1)
    assert isinstance(prompt, str)
    assert len(prompt) > 50
    assert "162.4" in prompt


def test_summarizer_fallback_without_llm():
    """Without an LLM server, summarizer returns a formatted text summary."""
    summarizer = ActivitySummarizer(llm_url=None)
    entries = [
        {"frequency_mhz": 98.5, "protocol": "fm", "result_type": "voice", "summary": "FM broadcast", "count": 10},
        {"frequency_mhz": 1090.0, "protocol": "adsb", "result_type": "position", "summary": "Aircraft", "count": 47},
    ]
    result = summarizer.summarize_sync(entries, hours=6)
    assert isinstance(result, str)
    assert "98.5" in result or "fm" in result.lower()
    assert "1090" in result or "adsb" in result.lower()


def test_summarizer_default_url():
    """Default LLM URL points to local llama-server."""
    summarizer = ActivitySummarizer()
    assert "localhost" in summarizer.llm_url or "127.0.0.1" in summarizer.llm_url
